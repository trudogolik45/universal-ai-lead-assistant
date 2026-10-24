<?php

namespace Espo\Modules\Uala\Tools;

use DateInterval;
use Espo\Core\Job\JobSchedulerFactory;
use Espo\Core\Utils\Config;
use Espo\Core\Utils\Log;
use Espo\Entities\User;
use Espo\Modules\Uala\Jobs\RetryN8nWebhook;
use Espo\ORM\Entity;
use Espo\ORM\EntityManager;

/**
 * Вызов webhook n8n из хуков модуля (ADR 0002): сразу, а не по расписанию, как встроенные
 * webhooks EspoCRM. Секрет — config ualaN8nHookSecret (env ESPOCRM_CONFIG_UALA_N8N_HOOK_SECRET),
 * n8n сверяет его с заголовком X-Uala-Secret.
 *
 * Таймаут короткий: сохранение записи не ждёт n8n. n8n не ответил 2xx — вызов повторяет задание
 * RetryN8nWebhook (daemon EspoCRM) с растущей паузой: config ualaN8nRetryDelay секунд × номер попытки.
 * Все попытки не прошли — сотрудник, сохранивший запись, получает уведомление в CRM.
 */
class N8nWebhook
{
    private const CONNECT_TIMEOUT_MS = 500;
    private const TIMEOUT_MS = 2000;
    private const RETRIES = 5;
    private const DEFAULT_RETRY_DELAY_SECONDS = 60;

    /** Что сотрудник узнаёт, когда n8n так и не принял вызов. */
    private const FAILURE_NOTICES = [
        'ualaEmployeeReplyUrl' => 'Wiadomość nie została wysłana do klienta: automatyzacja nie odpowiada. Wyślij ją ponownie później.',
    ];
    private const DEFAULT_FAILURE_NOTICE = 'Automatyzacja nie otrzymała tej zmiany: klient mógł nie dostać powiadomienia.';

    public function __construct(
        private Config $config,
        private Log $log,
        private User $user,
        private EntityManager $entityManager,
        private JobSchedulerFactory $jobSchedulerFactory,
    ) {}

    /**
     * @param string $urlParam config-ключ адреса webhook
     * @param array<string, mixed> $payload
     * @param Entity $source запись, о которой сообщаем: к ней привязано уведомление о сбое
     */
    public function post(string $urlParam, array $payload, Entity $source): void
    {
        $payload = $this->withCompany($payload);

        if ($this->send($urlParam, $payload)) {
            return;
        }

        $this->scheduleRetry([
            'urlParam' => $urlParam,
            'payload' => $payload,
            'sourceType' => $source->getEntityType(),
            'sourceId' => $source->getId(),
            'userId' => $this->employeeId(),
            'attempt' => 1,
        ]);
    }

    /**
     * Повтор из задания RetryN8nWebhook.
     *
     * @param array{urlParam: string, payload: array<string, mixed>, sourceType: string, sourceId: string,
     *     userId: ?string, attempt: int} $call
     */
    public function retry(array $call): void
    {
        if ($this->send($call['urlParam'], $call['payload'])) {
            return;
        }

        if ($call['attempt'] >= self::RETRIES) {
            $this->notifyFailure($call);

            return;
        }

        $this->scheduleRetry([...$call, 'attempt' => $call['attempt'] + 1]);
    }

    /**
     * У каждого Заказчика своя CRM (ADR 0001), а Клиент WhatsApp может писать нескольким Заказчикам:
     * n8n ищет его Беседу только у Заказчика этой CRM — config ualaCompany (env ESPOCRM_CONFIG_UALA_COMPANY),
     * slug Заказчика в буфере.
     *
     * @param array<string, mixed> $payload
     * @return array<string, mixed>
     */
    private function withCompany(array $payload): array
    {
        $company = $this->config->get('ualaCompany');

        return $company ? [...$payload, 'company' => $company] : $payload;
    }

    /** @param array<string, mixed> $payload */
    private function send(string $urlParam, array $payload): bool
    {
        $url = $this->config->get($urlParam);

        if (!$url) {
            $this->log->warning("Uala: {$urlParam} не задан, n8n не вызван");

            return true;
        }

        $curl = curl_init($url);
        curl_setopt_array($curl, [
            CURLOPT_POST => true,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'X-Uala-Secret: ' . $this->config->get('ualaN8nHookSecret', ''),
            ],
            CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE),
            CURLOPT_CONNECTTIMEOUT_MS => self::CONNECT_TIMEOUT_MS,
            CURLOPT_TIMEOUT_MS => self::TIMEOUT_MS,
            CURLOPT_RETURNTRANSFER => true,
        ]);

        if (curl_exec($curl) === false) {
            $this->log->error("Uala: n8n не принял вызов {$urlParam}: " . curl_error($curl));

            return false;
        }

        $status = curl_getinfo($curl, CURLINFO_RESPONSE_CODE);

        if ($status < 200 || $status >= 300) {
            $this->log->error("Uala: n8n ответил {$status} на вызов {$urlParam}");

            return false;
        }

        return true;
    }

    /** @param array<string, mixed> $call */
    private function scheduleRetry(array $call): void
    {
        $delay = (int) $this->config->get('ualaN8nRetryDelay', self::DEFAULT_RETRY_DELAY_SECONDS) * $call['attempt'];

        $this->jobSchedulerFactory->create()
            ->setClassName(RetryN8nWebhook::class)
            ->setData($call)
            ->setDelay(new DateInterval("PT{$delay}S"))
            ->schedule();
    }

    /** Сотрудник Заказчика, сохранивший запись; n8n (API) и системные задания уведомлений не ждут. */
    private function employeeId(): ?string
    {
        if ($this->user->isApi() || $this->user->isSystem()) {
            return null;
        }

        return $this->user->getId();
    }

    /** @param array<string, mixed> $call */
    private function notifyFailure(array $call): void
    {
        $this->log->error("Uala: n8n так и не принял вызов {$call['urlParam']} ({$call['sourceType']} {$call['sourceId']})");

        if (!$call['userId']) {
            return;
        }

        $notification = $this->entityManager->getNewEntity('Notification');
        $notification->set([
            'type' => 'Message',
            'userId' => $call['userId'],
            'message' => self::FAILURE_NOTICES[$call['urlParam']] ?? self::DEFAULT_FAILURE_NOTICE,
            'relatedType' => $call['sourceType'],
            'relatedId' => $call['sourceId'],
        ]);
        $this->entityManager->saveEntity($notification);
    }
}

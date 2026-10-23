<?php

namespace Espo\Modules\Uala\Hooks\Message;

use Espo\Core\Hook\Hook\AfterSave;
use Espo\Core\Utils\Config;
use Espo\Core\Utils\Log;
use Espo\Entities\User;
use Espo\ORM\Entity;
use Espo\ORM\EntityManager;
use Espo\ORM\Repository\Option\SaveOptions;

/**
 * Сообщение сотрудника уходит Клиенту за секунды: хук сразу зовёт webhook n8n (ADR 0002),
 * а n8n отправляет текст в Канал. Встроенные webhooks EspoCRM уходят по расписанию — не годятся.
 *
 * Таймаут короткий, ошибка только пишется в лог: сохранение Сообщения сотрудником не ломается
 * и не ждёт n8n. Адрес и секрет — config ualaEmployeeReplyUrl / ualaEmployeeReplySecret
 * (env ESPOCRM_CONFIG_UALA_EMPLOYEE_REPLY_URL / _SECRET).
 *
 * @implements AfterSave<Entity>
 */
class SendToClient implements AfterSave
{
    private const CONNECT_TIMEOUT_MS = 500;
    private const TIMEOUT_MS = 2000;

    public function __construct(
        private Config $config,
        private Log $log,
        private User $user,
        private EntityManager $entityManager,
    ) {}

    public function afterSave(Entity $entity, SaveOptions $options): void
    {
        // Сообщения n8n (API-пользователь) обратно в n8n не идут — иначе цикл.
        if (!$entity->isNew() || $entity->get('author') !== 'employee' || $this->user->isApi()) {
            return;
        }

        $url = $this->config->get('ualaEmployeeReplyUrl');

        if (!$url) {
            $this->log->warning('Uala: ualaEmployeeReplyUrl не задан, Сообщение сотрудника не отправлено');

            return;
        }

        $this->post($url, $this->payload($entity));
    }

    private function payload(Entity $message): array
    {
        $conversation = $this->entityManager->getEntityById('Conversation', $message->get('conversationId'));

        return [
            'crm_message_id' => $message->getId(),
            'channel' => $conversation?->get('channel'),
            'sender_id' => $conversation?->get('senderId'),
            'text' => $message->get('text'),
        ];
    }

    private function post(string $url, array $payload): void
    {
        $curl = curl_init($url);
        curl_setopt_array($curl, [
            CURLOPT_POST => true,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'X-Uala-Secret: ' . $this->config->get('ualaEmployeeReplySecret', ''),
            ],
            CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE),
            CURLOPT_CONNECTTIMEOUT_MS => self::CONNECT_TIMEOUT_MS,
            CURLOPT_TIMEOUT_MS => self::TIMEOUT_MS,
            CURLOPT_RETURNTRANSFER => true,
        ]);

        if (curl_exec($curl) === false) {
            $this->log->error('Uala: n8n не принял Сообщение сотрудника ' . $payload['crm_message_id'] . ': ' . curl_error($curl));
        }
    }
}

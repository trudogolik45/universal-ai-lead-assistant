<?php

namespace Espo\Modules\Uala\Tools;

use Espo\Core\Utils\Config;
use Espo\Core\Utils\Log;

/**
 * Вызов webhook n8n из хуков модуля (ADR 0002): сразу, а не по расписанию, как встроенные
 * webhooks EspoCRM. Секрет — config ualaN8nHookSecret (env ESPOCRM_CONFIG_UALA_N8N_HOOK_SECRET),
 * n8n сверяет его с заголовком X-Uala-Secret.
 *
 * Таймаут короткий, ошибка только пишется в лог: сохранение записи не ломается и не ждёт n8n.
 */
class N8nWebhook
{
    private const CONNECT_TIMEOUT_MS = 500;
    private const TIMEOUT_MS = 2000;

    public function __construct(
        private Config $config,
        private Log $log,
    ) {}

    /**
     * @param string $urlParam config-ключ адреса webhook
     * @param array<string, mixed> $payload
     */
    public function post(string $urlParam, array $payload): void
    {
        $url = $this->config->get($urlParam);

        if (!$url) {
            $this->log->warning("Uala: {$urlParam} не задан, n8n не вызван");

            return;
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
        }
    }
}

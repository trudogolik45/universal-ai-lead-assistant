<?php

namespace Espo\Modules\Uala\Jobs;

use Espo\Core\Job\Job;
use Espo\Core\Job\Job\Data;
use Espo\Modules\Uala\Tools\N8nWebhook;

/**
 * Повтор вызова n8n, который хук модуля не смог сделать сразу (Tools/N8nWebhook).
 */
class RetryN8nWebhook implements Job
{
    public function __construct(private N8nWebhook $n8n) {}

    public function run(Data $data): void
    {
        // Данные задания хранятся как JSON-объект: обратно в массив, как его собрал N8nWebhook.
        $this->n8n->retry(json_decode(json_encode($data->getRaw()), true));
    }
}

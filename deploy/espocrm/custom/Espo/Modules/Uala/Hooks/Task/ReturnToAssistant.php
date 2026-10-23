<?php

namespace Espo\Modules\Uala\Hooks\Task;

use Espo\Core\Hook\Hook\AfterSave;
use Espo\Modules\Uala\Tools\N8nWebhook;
use Espo\ORM\Entity;
use Espo\ORM\Repository\Option\SaveOptions;

/**
 * Сотрудник закрыл Задачу по Беседе — n8n возвращает Беседу Ассистенту, если это Задача
 * «Передача человеку» (n8n узнаёт её по id). Адрес — config ualaTaskDoneUrl
 * (env ESPOCRM_CONFIG_UALA_TASK_DONE_URL).
 *
 * @implements AfterSave<Entity>
 */
class ReturnToAssistant implements AfterSave
{
    private const DONE_STATUSES = ['Completed', 'Canceled'];

    public function __construct(private N8nWebhook $n8n) {}

    public function afterSave(Entity $entity, SaveOptions $options): void
    {
        if (
            $entity->get('parentType') !== 'Conversation'
            || !$entity->isAttributeChanged('status')
            || !in_array($entity->get('status'), self::DONE_STATUSES, true)
        ) {
            return;
        }

        $this->n8n->post('ualaTaskDoneUrl', ['crm_task_id' => $entity->getId()]);
    }
}

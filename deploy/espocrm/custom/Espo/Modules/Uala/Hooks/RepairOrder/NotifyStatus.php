<?php

namespace Espo\Modules\Uala\Hooks\RepairOrder;

use Espo\Core\Hook\Hook\AfterSave;
use Espo\Modules\Uala\Tools\ClientConversations;
use Espo\Modules\Uala\Tools\N8nWebhook;
use Espo\ORM\Entity;
use Espo\ORM\Repository\Option\SaveOptions;

/**
 * Мастер сменил статус Заказ-наряда — n8n сразу узнаёт новый статус и Беседы Клиента и сам решает,
 * что сообщить Клиенту (внутренние статусы Клиенту не уходят) и нужна ли Задача «составить Смету».
 * Адрес — config ualaRepairStatusUrl (env ESPOCRM_CONFIG_UALA_REPAIR_STATUS_URL).
 *
 * @implements AfterSave<Entity>
 */
class NotifyStatus implements AfterSave
{
    public function __construct(
        private N8nWebhook $n8n,
        private ClientConversations $clientConversations,
    ) {}

    public function afterSave(Entity $entity, SaveOptions $options): void
    {
        if (!$entity->isAttributeChanged('status')) {
            return;
        }

        $this->n8n->post('ualaRepairStatusUrl', [
            'crm_repair_order_id' => $entity->getId(),
            'name' => $entity->get('name'),
            'status' => $entity->get('status'),
            'conversations' => $this->clientConversations->of($entity->get('contactId')),
        ]);
    }
}

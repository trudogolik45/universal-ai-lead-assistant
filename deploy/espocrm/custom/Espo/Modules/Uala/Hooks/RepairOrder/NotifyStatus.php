<?php

namespace Espo\Modules\Uala\Hooks\RepairOrder;

use Espo\Core\Hook\Hook\AfterSave;
use Espo\Modules\Uala\Tools\N8nWebhook;
use Espo\ORM\Entity;
use Espo\ORM\EntityManager;
use Espo\ORM\Repository\Option\SaveOptions;

/**
 * Мастер сменил статус Заказ-наряда — n8n сразу узнаёт новый статус и Беседы Клиента и сам решает,
 * что сообщить Клиенту (внутренние статусы Клиенту не уходят). Адрес — config ualaRepairStatusUrl
 * (env ESPOCRM_CONFIG_UALA_REPAIR_STATUS_URL).
 *
 * @implements AfterSave<Entity>
 */
class NotifyStatus implements AfterSave
{
    public function __construct(
        private N8nWebhook $n8n,
        private EntityManager $entityManager,
    ) {}

    public function afterSave(Entity $entity, SaveOptions $options): void
    {
        if (!$entity->isAttributeChanged('status')) {
            return;
        }

        $this->n8n->post('ualaRepairStatusUrl', [
            'crm_repair_order_id' => $entity->getId(),
            'status' => $entity->get('status'),
            'conversations' => $this->conversations($entity->get('contactId')),
        ]);
    }

    /**
     * Адреса Клиента в Каналах: n8n по ним находит Беседу.
     *
     * @return list<array{channel: string, sender_id: string}>
     */
    private function conversations(?string $contactId): array
    {
        if (!$contactId) {
            return [];
        }

        $conversations = $this->entityManager
            ->getRDBRepository('Conversation')
            ->where(['contactId' => $contactId])
            ->find();

        $addresses = [];
        foreach ($conversations as $conversation) {
            $addresses[] = ['channel' => $conversation->get('channel'), 'sender_id' => $conversation->get('senderId')];
        }

        return $addresses;
    }
}

<?php

namespace Espo\Modules\Uala\Hooks\Estimate;

use Espo\Core\Hook\Hook\AfterSave;
use Espo\Modules\Uala\Tools\ClientConversations;
use Espo\Modules\Uala\Tools\N8nWebhook;
use Espo\ORM\Entity;
use Espo\ORM\EntityManager;
use Espo\ORM\Repository\Option\SaveOptions;

/**
 * Сменился статус Сметы — n8n сразу узнаёт его, сумму и Беседы Клиента Заказ-наряда: готовую Смету
 * отправляет Клиенту и ведёт цепочку уточнений, на любом другом статусе цепочку останавливает.
 * Адрес — config ualaEstimateUrl (env ESPOCRM_CONFIG_UALA_ESTIMATE_URL).
 *
 * @implements AfterSave<Entity>
 */
class NotifyStatus implements AfterSave
{
    public function __construct(
        private N8nWebhook $n8n,
        private ClientConversations $clientConversations,
        private EntityManager $entityManager,
    ) {}

    public function afterSave(Entity $entity, SaveOptions $options): void
    {
        if (!$entity->isAttributeChanged('status')) {
            return;
        }

        $this->n8n->post('ualaEstimateUrl', [
            'crm_estimate_id' => $entity->getId(),
            'crm_repair_order_id' => $entity->get('repairOrderId'),
            'name' => $entity->get('name'),
            'status' => $entity->get('status'),
            'amount' => $entity->get('amount'),
            'currency' => $entity->get('amountCurrency'),
            'conversations' => $this->clientConversations->of($this->contactId($entity->get('repairOrderId'))),
        ], $entity);
    }

    private function contactId(?string $repairOrderId): ?string
    {
        if (!$repairOrderId) {
            return null;
        }

        return $this->entityManager->getEntityById('RepairOrder', $repairOrderId)?->get('contactId');
    }
}

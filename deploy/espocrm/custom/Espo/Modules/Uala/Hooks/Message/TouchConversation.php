<?php

namespace Espo\Modules\Uala\Hooks\Message;

use Espo\Core\Hook\Hook\AfterSave;
use Espo\ORM\Entity;
use Espo\ORM\EntityManager;
use Espo\ORM\Repository\Option\SaveOptions;

/**
 * Новое Сообщение двигает «Ostatnia wiadomość» Беседы. Сохранение Беседы (не silent) EspoCRM
 * публикует по WebSocket (recordUpdate.Conversation.<id>): открытый экран Беседы перечитывает её,
 * и панель Сообщений (clientDefs relationshipPanels.messages.syncWithModel) показывает новое
 * Сообщение без перезагрузки страницы. Сообщение, дописанное retry позже, время назад не двигает.
 *
 * @implements AfterSave<Entity>
 */
class TouchConversation implements AfterSave
{
    public function __construct(private EntityManager $entityManager) {}

    public function afterSave(Entity $entity, SaveOptions $options): void
    {
        if (!$entity->isNew()) {
            return;
        }

        $conversation = $this->entityManager->getEntityById('Conversation', $entity->get('conversationId'));
        $sentAt = $entity->get('sentAt') ?? gmdate('Y-m-d H:i:s');

        if (!$conversation || $conversation->get('lastMessageAt') >= $sentAt) {
            return;
        }

        $conversation->set('lastMessageAt', $sentAt);
        $this->entityManager->saveEntity($conversation);
    }
}

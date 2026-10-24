<?php

namespace Espo\Modules\Uala\Hooks\Message;

use Espo\Core\Hook\Hook\AfterSave;
use Espo\Entities\User;
use Espo\Modules\Uala\Tools\N8nWebhook;
use Espo\ORM\Entity;
use Espo\ORM\EntityManager;
use Espo\ORM\Repository\Option\SaveOptions;

/**
 * Сообщение сотрудника уходит Клиенту за секунды: хук сразу зовёт webhook n8n
 * (config ualaEmployeeReplyUrl, env ESPOCRM_CONFIG_UALA_EMPLOYEE_REPLY_URL), а n8n отправляет текст в Канал.
 *
 * @implements AfterSave<Entity>
 */
class SendToClient implements AfterSave
{
    public function __construct(
        private N8nWebhook $n8n,
        private User $user,
        private EntityManager $entityManager,
    ) {}

    public function afterSave(Entity $entity, SaveOptions $options): void
    {
        // Сообщения n8n (API-пользователь) обратно в n8n не идут — иначе цикл.
        if (!$entity->isNew() || $entity->get('author') !== 'employee' || $this->user->isApi()) {
            return;
        }

        $this->n8n->post('ualaEmployeeReplyUrl', $this->payload($entity), $entity);
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
}

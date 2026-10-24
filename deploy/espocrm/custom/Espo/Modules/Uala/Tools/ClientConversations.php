<?php

namespace Espo\Modules\Uala\Tools;

use Espo\ORM\EntityManager;

/**
 * Адреса Клиента в Каналах — по ним n8n находит Беседу, куда написать Клиенту.
 */
class ClientConversations
{
    public function __construct(private EntityManager $entityManager) {}

    /**
     * @return list<array{channel: string, sender_id: string}>
     */
    public function of(?string $contactId): array
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

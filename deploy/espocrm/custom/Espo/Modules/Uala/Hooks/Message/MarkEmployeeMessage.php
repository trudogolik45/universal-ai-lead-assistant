<?php

namespace Espo\Modules\Uala\Hooks\Message;

use Espo\Core\Hook\Hook\BeforeSave;
use Espo\Entities\User;
use Espo\ORM\Entity;
use Espo\ORM\Repository\Option\SaveOptions;

/**
 * Сообщение, которое сотрудник пишет в Беседе, — исходящее от сотрудника, время отправки — сейчас.
 * Направление и автора сотрудник не выбирает. Сообщения Клиента и Ассистента пишет n8n
 * под API-пользователем: их поля не трогаем.
 *
 * @implements BeforeSave<Entity>
 */
class MarkEmployeeMessage implements BeforeSave
{
    public function __construct(private User $user) {}

    public function beforeSave(Entity $entity, SaveOptions $options): void
    {
        if (!$entity->isNew() || !$this->isEmployee()) {
            return;
        }

        $entity->set([
            'direction' => 'out',
            'author' => 'employee',
            'sentAt' => gmdate('Y-m-d H:i:s'),
        ]);
    }

    private function isEmployee(): bool
    {
        return $this->user->isRegular() || ($this->user->isAdmin() && !$this->user->isSystem());
    }
}

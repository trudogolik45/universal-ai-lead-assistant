-- Сообщение в Беседе CRM (переходник CRM, сейчас EspoCRM). crm_message_id — id записи в CRM,
-- пусто, пока запись не удалась. crm_claimed_at — когда запись взяли в работу: недописанное
-- и уже не свежее повторяет retry. Сообщения до этой миграции в CRM не переносятся.
alter table messages
    add column crm_message_id text,
    add column crm_claimed_at timestamptz;

create index messages_crm_pending on messages (crm_claimed_at) where crm_message_id is null;

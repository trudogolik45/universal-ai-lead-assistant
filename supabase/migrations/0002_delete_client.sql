-- Удаление данных Клиента по запросу (RODO/GDPR): его Беседы, а каскадом — Сообщения и Заявки.
-- Возвращает число удалённых Бесед.
create function delete_client(p_company_id uuid, p_channel text, p_sender_id text)
returns integer
language sql as $$
    with deleted as (
        delete from conversations
        where company_id = p_company_id
          and channel = p_channel
          and sender_id = p_sender_id
        returning 1
    )
    select count(*)::integer from deleted;
$$;

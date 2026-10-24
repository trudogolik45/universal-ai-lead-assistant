-- Буфер входящих: сообщение Канала ложится сюда до любой обработки, Meta получает 200 после записи.
-- Уникальность по id сообщения провайдера: дубль вебхука второй строки не создаёт и не обрабатывается.
-- processed_at пуст, пока обработка не дошла до конца: такую строку повторяет retry.
create table inbox (
    id uuid primary key default gen_random_uuid(),
    provider_message_id text not null unique,
    -- Входящее Сообщение в единой форме Каналов: channel, account_id, sender_id, provider_message_id, text.
    message jsonb not null,
    received_at timestamptz not null default now(),
    -- Когда обработку взяли в работу (основной поток или retry): свежую взятую retry не трогает.
    claimed_at timestamptz not null default now(),
    processed_at timestamptz
);

create index inbox_unprocessed on inbox (claimed_at) where processed_at is null;

-- Очередь отправки с повторами (спека #17): сообщение Клиенту, которое больше никто не повторит
-- (ответ Ассистента и сотрудника, статус ремонта), ложится сюда до отправки. sent_at пуст, пока Канал
-- не принял сообщение: такую строку retry-leads отправляет снова, взятую больше 5 минут назад.
-- Беседа удаляется (delete_client) — её очередь вместе с ней.
create table outbox (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references conversations (id) on delete cascade,
    text text not null,
    -- Шаблон Автоматизации ({name, parameters}) — как его передал вызывающий send-to-client.
    template jsonb,
    created_at timestamptz not null default now(),
    claimed_at timestamptz not null default now(),
    attempts integer not null default 1,
    sent_at timestamptz
);

create index outbox_unsent on outbox (claimed_at) where sent_at is null;

-- Буфер входящих: сколько раз обработка сообщения упала и ушёл ли разработчикам алерт «AI не отвечает».
alter table inbox
    add column failures integer not null default 0,
    add column alert_sent_at timestamptz;

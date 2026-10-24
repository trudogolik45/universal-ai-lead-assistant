-- Отзывы после ремонта (workflow repair-status, handle-message, create-rating-task).
-- google_review_url — ссылка «оставить отзыв в Google» Заказчика: её получает Клиент за оценку 4–5.
alter table companies add column google_review_url text;

-- Запрос оценки 1–5 по закрытому Заказ-наряду: строку ставит первый запрос, повторное закрытие
-- того же Заказ-наряда второго не шлёт. conversation_id — Беседа, куда ушёл запрос: ответ Клиента
-- ждём от того же Клиента в том же Канале (Беседа могла закрыться и открыться новая).
-- rating_message_id — Сообщение Клиента с оценкой: его повторная обработка из буфера оценку не теряет.
-- task_claimed_at / crm_task_id — Задача человеку за оценку 1–3, по образцу Передачи человеку.
create table repair_ratings (
    company_id uuid not null references companies (id) on delete cascade,
    crm_repair_order_id text not null,
    conversation_id uuid not null,
    asked_at timestamptz not null default now(),
    rating smallint check (rating between 1 and 5),
    rating_message_id uuid references messages (id) on delete set null,
    rated_at timestamptz,
    task_claimed_at timestamptz,
    crm_task_id text,
    primary key (company_id, crm_repair_order_id),
    foreign key (conversation_id, company_id) references conversations (id, company_id) on delete cascade
);

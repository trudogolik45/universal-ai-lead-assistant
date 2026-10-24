-- Смета (workflow repair-status и estimates).
--
-- estimate_tasks — Задача человеку «составить Смету» на Заказ-наряд, одна: строку ставит вызов,
-- взявший создание в работу (claimed_at), crm_task_id — задача создана. Не создалась — следующий
-- статус «машину приняли» берёт её снова через 5 минут.
create table estimate_tasks (
    crm_repair_order_id text primary key,
    claimed_at timestamptz not null default now(),
    crm_task_id text
);

-- estimates — готовая Смета и Беседа, куда она уходит (где Клиент писал последним). ready_at — когда
-- мастер отметил Смету готовой; stopped_at — сотрудник сменил статус Сметы (Клиент принял, отказался,
-- Смету правят): цепочка уточнений остановлена.
create table estimates (
    crm_estimate_id text primary key,
    company_id uuid not null,
    conversation_id uuid not null,
    crm_repair_order_id text not null,
    name text not null,
    amount numeric(12, 2) not null,
    currency text not null,
    ready_at timestamptz not null default now(),
    stopped_at timestamptz,
    foreign key (conversation_id, company_id)
        references conversations (id, company_id) on delete cascade
);

-- estimate_steps — шаги цепочки по порядку: Смета ушла (sent), два уточнения (reminder_1, reminder_2),
-- Задача человеку «Клиент молчит» (silent_task). Строку ставит запуск, взявший шаг в работу; done_at —
-- шаг сделан. Не сделан — следующий запуск берёт его снова через 5 минут.
create table estimate_steps (
    crm_estimate_id text not null references estimates (crm_estimate_id) on delete cascade,
    step text not null check (step in ('sent', 'reminder_1', 'reminder_2', 'silent_task')),
    claimed_at timestamptz not null default now(),
    done_at timestamptz,
    primary key (crm_estimate_id, step)
);

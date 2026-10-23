-- Запись Клиента в свободный слот (переходник CRM, сейчас EspoCRM Meeting).
-- appointments — поставленные Ассистентом Записи: id в CRM нужен записи Заявки, чтобы привязать
-- Запись к Клиенту и Автомобилю, а Ассистенту — чтобы не записать Клиента второй раз.
create table appointments (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies (id) on delete cascade,
    lead_id uuid not null references leads (id) on delete cascade,
    starts_at timestamptz not null,
    ends_at timestamptz not null,
    crm_meeting_id text not null,
    created_at timestamptz not null default now()
);

create index appointments_lead on appointments (lead_id, created_at);

-- Блокировка слота на время «проверить слот в CRM → создать Запись»: два Клиента не ставят
-- Запись на одно время одновременно. Блокировку снимает поставленная Запись; брошенная
-- (упал workflow) истекает в locked_until.
create table slot_locks (
    company_id uuid not null references companies (id) on delete cascade,
    starts_at timestamptz not null,
    locked_until timestamptz not null,
    primary key (company_id, starts_at)
);

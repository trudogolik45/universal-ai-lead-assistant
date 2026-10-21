-- Заказчик, База знаний, Беседа, Сообщение, Заявка. Термины: GLOSSARY.md.
-- Статусы и перечисления — text + check: n8n передаёт параметры строками без приведения типов.

create function set_updated_at() returns trigger
language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

-- Заказчик: профиль, Режим ответа, Канал доставки, идентификаторы Каналов.
create table companies (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    name text not null,
    default_language text not null default 'pl'
        check (default_language in ('pl', 'en', 'ru')),
    reply_mode text not null default 'auto'
        check (reply_mode in ('auto', 'silent')),
    required_fields text[] not null default '{name,contact,service}'
        check (required_fields <@ array['name', 'contact', 'service', 'description', 'desired_date']),
    handoff_rules text not null default '',
    ai_model text not null default 'openai/gpt-6-luna',
    -- Канал доставки
    sheets_spreadsheet_id text,
    sheets_sheet_name text not null default 'Leads',
    telegram_chat_id text,
    crm_webhook_url text,
    -- Идентификаторы Каналов: по ним входящее сообщение находит Заказчика
    messenger_page_id text unique,
    whatsapp_phone_number_id text unique,
    instagram_account_id text unique,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create trigger companies_updated_at before update on companies
    for each row execute function set_updated_at();

-- База знаний: уходит в промпт целиком.
create table knowledge_items (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies (id) on delete cascade,
    kind text not null check (kind in ('service', 'faq', 'hours', 'rule')),
    title text not null,
    body text not null default '',
    price numeric(10, 2) check (price >= 0),
    position int not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    -- Естественный ключ для идемпотентных сидов
    unique (company_id, kind, title)
);

create trigger knowledge_items_updated_at before update on knowledge_items
    for each row execute function set_updated_at();

-- Беседа: переписка с одним Клиентом в одном Канале.
create table conversations (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies (id) on delete cascade,
    channel text not null check (channel in ('messenger', 'whatsapp', 'instagram')),
    sender_id text not null,
    status text not null default 'open'
        check (status in ('open', 'handoff', 'closed')),
    language text check (language in ('pl', 'en', 'ru')),
    last_message_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    -- Цель составных FK: Сообщение и Заявка не могут сослаться на Беседу другого Заказчика.
    unique (id, company_id)
);

-- Одна активная Беседа на (Заказчик, Канал, Клиент): handoff тоже активна.
create unique index conversations_one_active_per_client
    on conversations (company_id, channel, sender_id)
    where status in ('open', 'handoff');

-- Закрытие Бесед после 7 дней тишины.
create index conversations_active_by_last_message
    on conversations (last_message_at)
    where status in ('open', 'handoff');

create trigger conversations_updated_at before update on conversations
    for each row execute function set_updated_at();

-- Сообщение: id сообщения провайдера уникален — дубль вебхука не обрабатывается повторно.
create table messages (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null,
    conversation_id uuid not null,
    direction text not null check (direction in ('in', 'out')),
    text text not null,
    provider_message_id text unique,
    created_at timestamptz not null default now(),
    foreign key (conversation_id, company_id)
        references conversations (id, company_id) on delete cascade
);

-- Последние 20 сообщений Беседы для промпта.
create index messages_by_conversation on messages (conversation_id, created_at);

-- Заявка: одна на Беседу. Статус доставки — пустая или заполненная колонка *_at.
create table leads (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null,
    conversation_id uuid not null unique,
    status text not null default 'new'
        check (status in ('new', 'collecting', 'qualified', 'needs_human', 'closed')),
    name text,
    contact text,
    service text,
    description text,
    desired_date text,
    intent text
        check (intent in ('price', 'booking', 'consultation', 'estimate', 'complaint', 'other')),
    missing_fields text[] not null default '{}',
    handoff_reason text,
    sheets_delivered_at timestamptz,
    telegram_sent_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (conversation_id, company_id)
        references conversations (id, company_id) on delete cascade
);

-- Retry: недоставленные Заявки.
create index leads_undelivered
    on leads (status)
    where sheets_delivered_at is null or telegram_sent_at is null;

create trigger leads_updated_at before update on leads
    for each row execute function set_updated_at();

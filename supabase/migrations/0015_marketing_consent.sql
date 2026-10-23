-- Согласие на рекламу (главное — Contact.marketingConsent в CRM). В Заявке — ответ Клиента в её Беседе
-- (null — не отвечал), его пишет в CRM write-lead-to-crm, и время, когда Ассистент спросил: Клиента
-- спрашивают один раз, во всех его Беседах в Канале.
alter table leads
    add column marketing_consent boolean,
    add column marketing_consent_asked_at timestamptz;

-- Напоминания о ТО и сезонной замене шин (workflow marketing-reminders): одно на Клиента и повод
-- (campaign: 'tyres:2026-autumn', 'service:<id Записи>'). Клиент — (Заказчик, Канал, отправитель), как
-- у Беседы; conversation_id — Беседа, через которую ушло: удаление Клиента (delete_client) удаляет и эти
-- строки. claimed_at — запуск взял напоминание, sent_at — Клиенту ушло; не ушло — повтор через 5 минут.
create table marketing_messages (
    company_id uuid not null references companies (id) on delete cascade,
    channel text not null,
    sender_id text not null,
    campaign text not null,
    conversation_id uuid not null references conversations (id) on delete cascade,
    claimed_at timestamptz not null default now(),
    sent_at timestamptz,
    primary key (company_id, channel, sender_id, campaign)
);

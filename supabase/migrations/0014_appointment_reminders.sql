-- Напоминания о Записи за 24 и за 2 часа (workflow appointment-reminders): одно на каждый срок.
-- Строку ставит запуск, взявший напоминание в работу (claimed_at); sent_at — Клиенту ушло.
-- Не ушло (сбой Канала или SMSAPI) — следующий запуск берёт его снова через 5 минут, пока срок не прошёл.
create table appointment_reminders (
    appointment_id uuid not null references appointments (id) on delete cascade,
    kind text not null check (kind in ('24h', '2h')),
    claimed_at timestamptz not null default now(),
    sent_at timestamptz,
    primary key (appointment_id, kind)
);

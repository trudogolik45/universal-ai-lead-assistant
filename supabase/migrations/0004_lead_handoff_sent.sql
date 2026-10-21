-- Сводка Передачи человеку отмечается отдельно от «Новой заявки»: после возврата Ассистенту
-- и qualified уведомление о Заявке всё равно уходит (telegram_sent_at не занят сводкой).
alter table leads add column handoff_sent_at timestamptz;

drop index leads_undelivered;
create index leads_undelivered
    on leads (status)
    where sheets_delivered_at is null or telegram_sent_at is null or handoff_sent_at is null;

-- Алерт «AI не отвечает» дошёл до группы Заказчика. Пусто при ai_failed_at — алерт повторит retry.
alter table messages add column ai_alert_sent_at timestamptz;

-- Сбои до этой миграции retry не дошлёт: их алерты уже ушли или уже неактуальны.
update messages set ai_alert_sent_at = ai_failed_at where ai_failed_at is not null;

-- Канал доставки ушёл (ADR 0001): Заявки и Задачи человеку — в EspoCRM, Google-таблицы,
-- Telegram Заказчика и CRM-webhook больше нет. Алерт «AI не отвечает» идёт разработчикам
-- (env ALERT_TELEGRAM_CHAT_ID), messages.ai_alert_sent_at остаётся.
drop index leads_undelivered;

alter table leads
    drop column sheets_delivered_at,
    drop column telegram_sent_at,
    drop column handoff_sent_at;

alter table companies
    drop column sheets_spreadsheet_id,
    drop column sheets_sheet_name,
    drop column telegram_chat_id,
    drop column crm_webhook_url;

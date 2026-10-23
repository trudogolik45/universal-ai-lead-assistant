-- Задача человеку в CRM на Передачу человеку (переходник CRM, сейчас EspoCRM Task).
-- handoff_task_id — id задачи в CRM, пусто, пока создание не удалось; handoff_task_claimed_at —
-- когда создание взяли в работу: несозданное и уже не свежее повторяет retry.
-- Новая Передача человеку той же Заявки сбрасывает оба поля: нужна новая задача.
alter table leads
    add column handoff_task_id text,
    add column handoff_task_claimed_at timestamptz;

create index leads_handoff_task_pending on leads (handoff_task_claimed_at)
    where status = 'needs_human' and handoff_task_id is null;

-- Пометка для алерта: Ассистент не ответил на входящее Сообщение — OpenRouter упал дважды подряд.
alter table messages add column ai_failed_at timestamptz;

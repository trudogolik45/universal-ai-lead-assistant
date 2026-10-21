# CRM через webhook

Заявку можно получать в свою CRM (или Make, Zapier, свой сервис): Ассистент отправляет её JSON
POST-запросом на URL Заказчика. Готовых интеграций с конкретными CRM нет — только этот webhook.

## Подключение

1. Получить в CRM входящий webhook-URL, принимающий `POST` с JSON (HTTPS).
2. Записать его в профиль Заказчика:
   ```sql
   update companies set crm_webhook_url = 'https://crm.example.com/hooks/leads'
   where slug = 'uniwersalny-serwis';
   ```
   Отключить — `set crm_webhook_url = null`.

Правка действует сразу, перезапуск n8n не нужен.

## Когда уходит

Workflow `deliver-lead` (`n8n/workflows/deliver-lead.json`) вызывается, когда Заявка впервые
становится `qualified` (все обязательные поля собраны, см. [knowledge-base.md](knowledge-base.md)).

- Если у Заказчика задана Google-таблица (`sheets_spreadsheet_id`) — сначала строка в таблицу,
  затем, только после успешной записи, POST в CRM.
- Если таблица не задана — сразу POST в CRM.
- Таблица недоступна — в CRM ничего не уходит. Workflow `retry-leads` раз в 5 минут дописывает
  такую Заявку в таблицу и тогда же отправляет её в CRM.
- Повторная квалификация той же Заявки второй раз в таблицу и CRM не пишет.

Запрос один, без повторов: ответ CRM не сохраняется, ошибка CRM (не 2xx, таймаут 30 с) не
повторяется и на Клиента и таблицу не влияет. Если важна гарантированная доставка — CRM-webhook
должен сам принимать запрос быстро и надёжно (например, очередь в Make/Zapier).

## Формат

`POST <crm_webhook_url>`, `Content-Type: application/json`, без авторизации и подписи (секрет
можно передать в самом URL, например `?token=...`).

```json
{
  "lead_id": "6f1c1a52-6a8e-4c0e-9a51-6f8d2a9e1b10",
  "company_id": "1b4c8e6a-0f3d-4a7e-8c2b-5d9e7f1a2c34",
  "conversation_id": "9e2d4b7c-3a1f-4e6d-b8c5-2f7a9d1e3b56",
  "channel": "messenger",
  "status": "qualified",
  "name": "Anna Kowalska",
  "contact": "+48 600 100 200",
  "service": "Montaż mebli",
  "description": "Szafa z IKEA",
  "desired_date": "piątek rano",
  "intent": "booking",
  "created_at": "2026-10-21T09:15:42.120Z"
}
```

| Поле | Тип | Значение |
|---|---|---|
| `lead_id` | uuid | id Заявки (`leads.id`), ключ для дедупликации на стороне CRM |
| `company_id` | uuid | Заказчик |
| `conversation_id` | uuid | Беседа, из которой собрана Заявка |
| `channel` | string | Канал: `messenger` (позже `whatsapp`, `instagram`) |
| `status` | string | Статус Заявки на момент отправки, обычно `qualified` |
| `name`, `contact`, `service`, `description` | string \| null | Данные Заявки; необязательные поля могут быть `null` |
| `desired_date` | string \| null | Желаемая дата словами Клиента («piątek rano»), не нормализуется |
| `intent` | string \| null | `price`, `booking`, `consultation`, `estimate`, `complaint`, `other` |
| `created_at` | string | Когда создана Заявка (первое Сообщение Беседы), ISO 8601 |

Проверка формата — тест `tests/test_lead_delivery.py::test_lead_json_is_posted_to_crm_webhook_when_set`.

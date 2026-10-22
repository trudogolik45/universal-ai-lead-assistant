# База знаний и профиль Заказчика

Профиль Заказчика и База знаний лежат в Supabase (таблицы `companies` и `knowledge_items`,
схема — `supabase/migrations/0001_schema.sql`). Отдельного интерфейса нет: правки — SQL в
Supabase SQL Editor или `psql "$DATABASE_URL"`. Ассистент читает профиль и Базу знаний заново
на каждое входящее Сообщение, поэтому правка действует со следующего Сообщения, без перезапуска
n8n и без правки workflow.

Ниже `uniwersalny-serwis` — slug демо-профиля; slug своего Заказчика: `select slug, name from companies;`.

## Что уходит в промпт

На каждое Сообщение workflow `meta-webhook` собирает:

- `companies.name`, `default_language`, `handoff_rules`, `required_fields`, `ai_model`;
- всю Базу знаний Заказчика (`kind`, `title`, `body`, `price`) — целиком, без поиска, порядок:
  `kind`, затем `position`;
- текущую Заявку и последние 20 Сообщений Беседы.

Ассистент отвечает только по Базе знаний: цен, услуг и сроков, которых в ней нет, он не называет,
а передаёт Беседу человеку. Поэтому всё, о чём Клиент может спросить, должно быть в Базе знаний.

## База знаний (`knowledge_items`)

| Поле | Значение |
|---|---|
| `kind` | `service` — услуга, `faq` — вопрос-ответ, `hours` — часы работы, `rule` — правило (например, «термин подтверждает владелец») |
| `title` | Название услуги или вопрос. Уникально в паре с `kind` у одного Заказчика |
| `body` | Описание или ответ |
| `price` | Цена в PLN (`numeric(10,2)`), только для услуг; `null` — цены нет, Ассистент её не назовёт |
| `position` | Порядок внутри `kind` |

Добавить или обновить услугу (повтор не создаёт дубль):

```sql
insert into knowledge_items (company_id, kind, title, body, price, position)
select id, 'service', 'Montaż karnisza', 'Montaż jednego karnisza z wierceniem.', 90.00, 5
from companies where slug = 'uniwersalny-serwis'
on conflict (company_id, kind, title)
do update set body = excluded.body, price = excluded.price, position = excluded.position;
```

Поменять цену:

```sql
update knowledge_items set price = 130.00
where kind = 'service' and title = 'Montaż mebli'
  and company_id = (select id from companies where slug = 'uniwersalny-serwis');
```

Добавить вопрос-ответ:

```sql
insert into knowledge_items (company_id, kind, title, body, position)
select id, 'faq', 'Czy wystawiacie fakturę?', 'Tak, fakturę VAT wystawiamy na życzenie.', 3
from companies where slug = 'uniwersalny-serwis';
```

Удалить запись:

```sql
delete from knowledge_items
where kind = 'faq' and title = 'Czy wystawiacie fakturę?'
  and company_id = (select id from companies where slug = 'uniwersalny-serwis');
```

Посмотреть Базу знаний целиком:

```sql
select kind, position, title, price, body
from knowledge_items
where company_id = (select id from companies where slug = 'uniwersalny-serwis')
order by kind, position;
```

## Обязательные поля (`companies.required_fields`)

Поля Заявки, без которых она не становится `qualified`. Допустимы только поля Заявки:
`name`, `contact`, `service`, `description`, `desired_date`. По умолчанию `{name,contact,service}`.

Список считает сервер, а не AI: Заявка с `qualified` от AI, но без обязательного поля, остаётся
`collecting`, недостающие поля — в `leads.missing_fields`. Ассистент дозапрашивает их у Клиента.

```sql
update companies set required_fields = '{name,contact,service,desired_date}'
where slug = 'uniwersalny-serwis';
```

Новый список действует для следующих Сообщений; уже `qualified` Заявки назад не откатываются.

## Правила передачи человеку (`companies.handoff_rules`)

Свободный текст: когда Ассистент передаёт Беседу человеку (жалобы, просьбы о скидке, крупные заказы).
Неизвестный Базе знаний вопрос и просьба позвать человека передаются всегда, без правил.

```sql
update companies
set handoff_rules = 'Przekaż człowiekowi: reklamacje, prośby o rabat, zlecenia powyżej 5 000 zł.'
where slug = 'uniwersalny-serwis';
```

## Режим ответа (`companies.reply_mode`)

- `auto` — Ассистент отвечает Клиенту и собирает Заявку.
- `silent` — Ассистент только собирает Заявку, Клиенту не пишет (исходящие Сообщения не сохраняются).

```sql
update companies set reply_mode = 'silent' where slug = 'uniwersalny-serwis';
```

Повторный сид (`scripts.seed`) не перезаписывает правки Заказчика: существующие строки он не трогает.

## Язык по умолчанию (`companies.default_language`)

Код ISO 639-1 одного из языков Европы (`pl`, `en`, `de`, `uk` и т. д., список — миграция
`0006_european_languages.sql`). Ассистент отвечает на языке Клиента; язык по умолчанию — когда язык
Клиента не определить.

```sql
update companies set default_language = 'en' where slug = 'uniwersalny-serwis';
```

## Модель AI (`companies.ai_model`)

Идентификатор модели OpenRouter, по умолчанию `openai/gpt-6-luna`. Модель должна поддерживать
`response_format` с `json_schema` (strict): ответ не по схеме Клиенту не уходит.

```sql
update companies set ai_model = '<id модели с openrouter.ai/models>' where slug = 'uniwersalny-serwis';
```

## Каналы доставки

Куда приходят Заявки, тоже в `companies`:

| Поле | Что это | Инструкция |
|---|---|---|
| `sheets_spreadsheet_id`, `sheets_sheet_name` | Google-таблица и лист (по умолчанию `Leads`) | [google-setup.md](google-setup.md) |
| `telegram_chat_id` | Группа Telegram для уведомлений и Передачи человеку | README, «Telegram» |
| `crm_webhook_url` | CRM-webhook | [crm-webhook.md](crm-webhook.md) |
| `messenger_page_id` | id страницы Facebook: по нему входящее Сообщение находит Заказчика | [meta-setup.md](meta-setup.md) |

```sql
update companies
set sheets_spreadsheet_id = '<id таблицы из URL>', telegram_chat_id = '-100...'
where slug = 'uniwersalny-serwis';
```

## Новый Заказчик

```sql
insert into companies (slug, name, default_language, reply_mode, required_fields, handoff_rules, messenger_page_id)
values ('nowa-firma', 'Nowa Firma', 'pl', 'auto', '{name,contact,service}',
        'Przekaż człowiekowi: reklamacje.', '<id страницы>');
```

Затем База знаний — запросами выше с `slug = 'nowa-firma'`.

## Удаление данных Клиента

По запросу Клиента (RODO) — все его Беседы, Сообщения и Заявки у одного Заказчика в одном Канале:

```sql
select delete_client(
  (select id from companies where slug = 'uniwersalny-serwis'), 'messenger', '<sender_id Клиента>'
);
```

Возвращает число удалённых Бесед. Следующее Сообщение Клиента начнёт новую Беседу без прежней истории.

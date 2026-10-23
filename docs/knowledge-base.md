# База знаний и профиль Заказчика

База знаний живёт в EspoCRM (сущность `KnowledgeItem`, меню «Baza wiedzy»): Заказчик правит
услуги, цены, график и адрес сам, в одном месте. Профиль Заказчика пока в Supabase (таблица
`companies`, схема — `supabase/migrations/`), правки — SQL в Supabase SQL Editor или
`psql "$DATABASE_URL"`. Ассистент читает профиль и Базу знаний заново на каждое входящее
Сообщение, поэтому правка действует со следующего Сообщения, без перезапуска n8n и без правки workflow.

Ниже `uniwersalny-serwis` — slug демо-профиля; slug своего Заказчика: `select slug, name from companies;`.

## Что уходит в промпт

На каждое Сообщение workflow `handle-message` собирает:

- `companies.name`, `default_language`, `handoff_rules`, `required_fields`, `ai_model`;
- всю Базу знаний из EspoCRM (`kind`, `name`, `description`, `price`, `priceFrom`) — целиком,
  без поиска, до 200 записей (предел REST API EspoCRM), порядок — по `kind`;
- текущую Заявку и последние 20 Сообщений Беседы.

Ассистент отвечает только по Базе знаний: цен, услуг и сроков, которых в ней нет, он не называет,
а передаёт Беседу человеку. Поэтому всё, о чём Клиент может спросить, должно быть в Базе знаний.

EspoCRM недоступна (две попытки подряд) — Ассистент цену не угадывает и Клиенту не отвечает:
Сообщение остаётся в буфере входящих, и retry (раз в 5 минут) обработает его, когда CRM вернётся.

## База знаний (EspoCRM, `KnowledgeItem`)

| Поле (в EspoCRM) | Значение |
|---|---|
| `name` (Nazwa) | Название услуги, вопрос FAQ или заголовок сведения |
| `kind` (Rodzaj) | `service` — услуга, `hours` — график работы, `company` — о компании: адрес, контакты, оплата, гарантия, марки; `faq` — вопрос-ответ; `rule` — правило (чего Ассистент не обещает) |
| `description` (Treść) | Описание, длительность, оговорки или ответ на вопрос |
| `price` (Cena, zł) | Цена в PLN с VAT; пусто — цены нет, Ассистент её не назовёт |
| `priceFrom` (Cena „od”) | Цена минимальная: Ассистент скажет «от … zł» |

Править — в EspoCRM: «Baza wiedzy» → запись → «Edytuj», новая — «Dodaj do bazy wiedzy».
API-пользователь `n8n` Базу знаний только читает (`scripts/espocrm_bootstrap.py`).

Демо-База знаний автосервиса AutoPro Service (`scripts/data/autopro_knowledge.json`, польский
перевод `docs/autopro_service_knowledge_base.md`) заливается в EspoCRM на VPS:

```sh
make espocrm-knowledge
```

Повтор безопасен: запись ищется по паре (`kind`, `name`), существующие не трогаются, правки
Заказчика не затираются.

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

Затем База знаний — в EspoCRM Заказчика, см. выше.

## Удаление данных Клиента

По запросу Клиента (RODO) — все его Беседы, Сообщения и Заявки у одного Заказчика в одном Канале:

```sql
select delete_client(
  (select id from companies where slug = 'uniwersalny-serwis'), 'messenger', '<sender_id Клиента>'
);
```

Возвращает число удалённых Бесед. Следующее Сообщение Клиента начнёт новую Беседу без прежней истории.

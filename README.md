# Universal AI Lead Assistant

AI-ассистент для входящих заявок малого бизнеса в Messenger, Instagram Direct и WhatsApp: отвечает Клиенту по Базе знаний
Заказчика, собирает Заявку и ведёт Беседу, Клиента, Заявку и Задачи человеку в EspoCRM Заказчика.
Спека: issue #17 (первая версия — #1), термины: `GLOSSARY.md`.

## Документы

| Документ | О чём |
|---|---|
| `GLOSSARY.md` | Термины: Заказчик, Клиент, Ассистент, Беседа, Заявка, Режим ответа, Передача человеку |
| [docs/deviations.md](docs/deviations.md) | Чем MVP отличается от ТЗ и почему |
| [docs/knowledge-base.md](docs/knowledge-base.md) | Как менять Базу знаний, обязательные поля, Режим ответа, модель AI; удаление данных Клиента |
| [docs/meta-setup.md](docs/meta-setup.md) | Для Заказчика: приложение Meta, страница, вебхук, токены |
| [docs/whatsapp-setup.md](docs/whatsapp-setup.md) | Для Заказчика: номер WhatsApp, постоянный токен, вебхук, шаблон «есть новости» |
| [docs/test-results.md](docs/test-results.md) | Сценарии спеки → тесты → результат последнего прогона |

## Как устроено

n8n (workflow в `n8n/workflows/`) + Postgres в Supabase (схема в `supabase/migrations/`).

| Workflow | Вход | Что делает |
|---|---|---|
| `meta-webhook` | `POST /webhook/meta` | Подпись Meta → сообщения в буфер входящих (`inbox`, дубль по id сообщения отсекается) → 200 Meta → `process-inbox` |
| `process-inbox` | вызов из других workflow | Сообщение из буфера через `handle-message`; дошло до конца — помечается обработанным, упало — остаётся в буфере |
| `handle-message` | вызов из других workflow | Заказчик по странице или номеру → Сообщение в Беседу → База знаний и свободные слоты из EspoCRM → OpenRouter → Запись в слот через `book-appointment` → ответ Клиенту через `send-to-client`, Заявка, Передача человеку; входящее и ответ — в CRM через `write-message-to-crm`, Заявка — через `write-lead-to-crm`, Задача человеку — через `create-handoff-task` |
| `send-to-client` | вызов из других workflow | Текст Клиенту в Канал его Беседы: Send API Messenger Platform (Messenger, Instagram Direct) или WhatsApp Cloud API; вне окна 24 часов после сообщения Клиента Messenger и Instagram — с меткой `HUMAN_AGENT`, WhatsApp — шаблон `news_update`. Автоматизация (на входе `template`): WhatsApp — этим шаблоном с параметрами, Клиенту из Messenger и Instagram — SMS через SMSAPI на телефон Заявки |
| `appointment-reminders` | раз в 5 минут; `POST /webhook/reminders` | Напоминания о Записи за 24 и за 2 часа: запланированные Записи (`Meeting` Planned) из CRM через переходник → один раз на срок (`appointment_reminders`) → `send-to-client` с шаблоном `appointment_reminder` |
| `write-message-to-crm` | вызов из других workflow | Сообщение из Postgres в Беседу Клиента в CRM через переходник; не вышло — остаётся недописанным (`messages.crm_message_id` пуст) для retry |
| `write-lead-to-crm` | вызов из других workflow | Заявка из Postgres в CRM с Клиентом и Автомобилем через переходник; не вышло или Заявка изменилась во время записи — её дописывает retry (`crm_leads`) |
| `employee-reply` | `POST /webhook/employee-reply` | Ответ сотрудника из EspoCRM (хук модуля Uala, секрет `X-Uala-Secret`): Беседа переходит в режим человека, Ассистент в ней молчит, текст — Клиенту через `send-to-client` |
| `task-done` | `POST /webhook/task-done` | Сотрудник закрыл Задачу «Передача человеку» в EspoCRM (хук модуля Uala, секрет `X-Uala-Secret`): Беседа снова у Ассистента, Заявка `collecting` или `qualified` по обязательным полям |
| `create-handoff-task` | вызов из других workflow | Передача человеку → Задача человеку в CRM через переходник: сводка на польском, ссылка на Беседу; не вышло — остаётся без задачи (`leads.handoff_task_id` пуст) для retry |
| `crm-adapter-espocrm` | вызов из других workflow | Переходник CRM, реализация EspoCRM REST API (`ESPOCRM_BASE_URL`, `ESPOCRM_API_KEY`). Операции: `record_message` — найти или создать Беседу по Каналу и id Клиента, добавить Сообщение; `create_task` — Задача человеку (Task) к Беседе: вид → команда (`handoff` → `Administratorzy`), в команде — активный сотрудник с наименьшим числом открытых задач; `record_lead` — Клиент Беседы (нет — создать и привязать), Автомобиль и Заявка — создать или обновить, Запись Заявки — привязать к ним; `free_slots` — свободные слоты по рабочему календарю (`WorkingTimeCalendar`) и Записям (`Meeting`); `book_appointment` — Запись (`Meeting`) в слот, если он ещё свободен; `planned_appointments` — запланированные Записи с началом в ближайшие `hours` часов; `report` — сколько Заявок и Записей создано за период, всего и по Каналам |
| `book-appointment` | вызов из других workflow | Запись Клиента в выбранный Ассистентом слот: блокировка слота в Postgres (`slot_locks`) → Запись в CRM через переходник → `appointments`; слот занят — Записи нет |
| `ai-alert` | вызов из других workflow | Алерт «AI не отвечает» в группу Telegram разработчиков (`ALERT_TELEGRAM_CHAT_ID`); Заказчик его не видит |
| `owner-report` | каждый день и каждый понедельник в 7:00; `POST /webhook/owner-report` | Отчёт владельцу письмом на польском: Заявки, Записи и конверсия по каждому Каналу за вчера или прошлую неделю, цифры из CRM через переходник |
| `retry-leads` | раз в 5 минут; `POST /webhook/retry` | Повтор необработанных сообщений буфера, дозапись Сообщений, Заявок и Задач человеку в CRM, недошедших алертов «AI не отвечает», закрытие Бесед после 7 дней тишины |

Рядом работает EspoCRM на своём Postgres (`deploy/espocrm`, ADR 0001 и 0002). В её модуле Uala
есть свои сущности: Беседа (`Conversation`), Сообщение (`Message`), Автомобиль (`Vehicle`)
и База знаний (`KnowledgeItem`) — её Ассистент читает на каждое Сообщение. Запись — встроенная
встреча `Meeting` со связью с Автомобилем; свободные слоты — по встроенному рабочему календарю
(`WorkingTimeCalendar`), см. docs/knowledge-base.md.
Заявка — встроенный `Lead` (по-польски «Zgłoszenie») со своими полями услуга (`service`), удобное время
(`desiredTime`) и связями с Клиентом, Автомобилем и Беседой; текст Заявки Ассистент пишет по-польски.
У Клиента (`Contact`) есть поле Согласие на рекламу (`marketingConsent`). n8n ходит в EspoCRM по
REST API под API-пользователем `n8n`, только через переходник `crm-adapter-espocrm`. Сообщения
в Беседе упорядочены по времени отправки (`Message.sentAt`), а не записи: дописанное retry встаёт
на своё место. Сообщение, которое сотрудник пишет в Беседе, хуки модуля Uala помечают исходящим
от сотрудника и сразу (таймаут 2 с) отправляют в n8n (`employee-reply`); встроенные webhooks
EspoCRM не используются — они уходят по расписанию. Так же сразу хук зовёт n8n (`task-done`), когда
сотрудник закрывает Задачу к Беседе (статус «Completed» или «Canceled»): если это Задача
«Передача человеку», Беседа возвращается Ассистенту. Беседа, в которую сотрудник написал сам
без Передачи человеку, остаётся у человека до закрытия после 7 дней тишины. n8n не ответил —
ошибка в логе EspoCRM, повтора нет.

Секреты — только в `.env` на VPS и в credentials n8n; в репо их нет. Имена и назначение всех
переменных — `.env.example`.

## Тесты

Нужны `uv` и Docker. Одна команда:

```
uv run pytest
```

Фикстуры (`tests/conftest.py`, `tests/stand.py`) сами поднимают стенд `docker-compose.test.yml`
(Postgres вместо Supabase и n8n той же версии, что в проде), применяют миграции, заливают
credentials и все workflow той же командой, что и прод (`scripts/n8n_sync.py`), и после прогона
удаляют контейнеры. Внешние API (OpenRouter, Meta Graph, Telegram, EspoCRM) изображает
фейк-сервер `tests/fake_server.py` на хосте, n8n ходит в него через `host.docker.internal`.
EspoCRM на главном шве — фейк с состоянием `tests/fake_espocrm.py` (фикстура `crm`: записи, которые
сделал n8n; `crm.unavailable()` — CRM лежит). Настоящая EspoCRM — только в контрактных тестах
`tests/test_espocrm.py`. Без Docker тесты пропускаются.

- `STAND_KEEP=1 uv run pytest` — оставить стенд после прогона (логи: `docker compose -p <проект>
  -f docker-compose.test.yml logs n8n`, порт n8n: `... port n8n 5678`).
- Имя compose-проекта — `COMPOSE_PROJECT_NAME`, по умолчанию своё на каждый checkout;
  порты хоста случайные, поэтому параллельные стенды не пересекаются.
- Настоящая EspoCRM (`tests/test_espocrm.py`, фикстура `espocrm`): образ из `deploy/espocrm`,
  отдельная база `espocrm` в Postgres стенда, установка с нуля на каждый прогон (около полутора
  минут), API-пользователь `n8n` — тем же `scripts/espocrm_bootstrap.py`, что в проде. Админка
  стенда — `docker compose -p <проект> -f docker-compose.test.yml port espocrm 80`, вход
  `admin` / `test-espocrm-admin`.

Какие сценарии покрыты и результат последнего прогона — [docs/test-results.md](docs/test-results.md).

## Деплой

n8n и EspoCRM работают на VPS `n3-vps` в Docker за Caddy: `https://n8n.n3spark.io` и
`https://crm.n3spark.io`.

```
интернет :443 → traefik (k3s, TLS passthrough по SNI) → Caddy :8443 (TLS, Let's Encrypt)
  → n8n 127.0.0.1:5678
  → EspoCRM 127.0.0.1:8080, её WebSocket /ws → 127.0.0.1:8081
```

Публичные 80/443 на VPS держит traefik из k3s, он обслуживает остальные `*.n3spark.io`.
Для `n8n.n3spark.io` и `crm.n3spark.io` он не расшифровывает TLS, а передаёт поток Caddy
(`deploy/traefik-passthrough.yaml`). Caddy получает сертификаты через TLS-ALPN-01.
HTTP→HTTPS редиректит traefik. Порт 8443 снаружи закрыт ufw, n8n и EspoCRM слушают только loopback.

Что нужно на ноутбуке: ssh-хост `n3-vps` в `~/.ssh/config`, `rsync`, `uv`, Docker (для `make check`).

1. Создать `.env` на VPS (`~/uala/.env`) из `.env.example` и сгенерировать
   `N8N_ENCRYPTION_KEY`, `ESPOCRM_DB_PASSWORD`, `ESPOCRM_ADMIN_PASSWORD`. Команда дописывает
   только недостающие ключи, заданные значения не трогает, так что её можно повторять:
   ```
   make env-init
   ```
2. Вписать секреты в `~/uala/.env` на VPS (`ssh n3-vps`, редактор). Все переменные из `.env`
   видны нодам n8n как `$env.*`.
3. Поднять или обновить стек:
   ```
   make deploy
   ```
   Команда валидирует конфиги (`make check`), копирует `deploy/` на VPS и применяет маршрут
   traefik. Потом она собирает образ EspoCRM и делает `docker compose up -d --wait`, а затем
   `bin/command rebuild` в EspoCRM. `.env` на VPS не трогает.
4. Открыть `https://n8n.n3spark.io` и при первом входе создать владельца n8n.
5. Схема и демо-профили в Supabase (идемпотентно, повтор безопасен):
   ```
   DATABASE_URL=... uv run python -m scripts.migrate
   DATABASE_URL=... DEMO_MESSENGER_PAGE_ID=... DEMO_WHATSAPP_PHONE_NUMBER_ID=... DEMO_INSTAGRAM_ACCOUNT_ID=... \
     uv run python -m scripts.seed
   ```
6. API-пользователь n8n в EspoCRM (повтор безопасен, ключ тот же):
   ```
   make espocrm-api-user
   ```
   Скрипт `scripts/espocrm_bootstrap.py` работает на VPS в контейнере uv. Под admin он создаёт
   роль и API-пользователя `n8n`, пишет его ключ в `ESPOCRM_API_KEY` в `~/uala/.env` и
   пересоздаёт n8n. Ключ не покидает VPS. Ещё он заводит группы сотрудников — команды
   `Administratorzy` и `Mechanicy` с ролью `Pracownicy`. Сотрудников в них добавляет Заказчик
   (Administration → Teams): Задача человеку достаётся только активному члену команды.
   Демо-База знаний и рабочий календарь AutoPro Service в EspoCRM (повтор безопасен, правки
   Заказчика не затирает):
   ```
   make espocrm-knowledge
   ```
7. Залить workflow:
   ```
   make workflows
   ```
   `scripts/n8n_sync.py push` по ssh: credentials Postgres из `DATABASE_URL` в `~/uala/.env`
   (передаются через stdin, на диск ноутбука не пишутся), импорт всех `n8n/workflows/*.json`,
   `publish:workflow` каждого и перезапуск n8n — вебхуки регистрируются только при старте.
   Повторять после каждой правки workflow.
8. Вебхук Meta — см. ниже. Telegram вебхука не держит: бот только шлёт алерты разработчикам.

После правки `.env` на VPS — `make deploy` (n8n перечитает переменные при пересоздании).
Версии образов: `N8N_VERSION`, `CADDY_VERSION`, `ESPOCRM_VERSION`, `POSTGRES_VERSION` в `.env`,
по умолчанию из `deploy/docker-compose.yml`.

### EspoCRM

Вход: `https://crm.n3spark.io`, пользователь `admin`, пароль — `ESPOCRM_ADMIN_PASSWORD` из
`~/uala/.env`. Этот пароль и `ESPOCRM_DB_PASSWORD` действуют только при первой установке.
Дальше пароль admin меняют в самой EspoCRM, а пароль базы хранится в томе Postgres.

Свои сущности и поля лежат в модуле `deploy/espocrm/custom/Espo/Modules/Uala`. Он входит в образ,
кликать в админке ничего не нужно:

- `Resources/metadata/entityDefs/<Сущность>.json` — поля, связи, индексы; `Contact.json`
  только дополняет встроенного Клиента;
- `scopes/`, `clientDefs/`, `Controllers/` — регистрация своей сущности и её REST API;
- `Resources/layouts/` — раскладки экранов, `Resources/i18n/pl_PL` и `en_US` — подписи.

Как обновить:

- Сущности или поля: правка модуля → `make deploy`. Образ пересобирается, `rebuild` добавляет
  таблицы и колонки. Удалённые поля остаются в базе колонками, EspoCRM их не удаляет.
  Новой сущности, с которой работает n8n, нужно право в `ROLE_ACL`
  (`scripts/espocrm_bootstrap.py`) и повтор `make espocrm-api-user`.
- Версия EspoCRM: `ESPOCRM_VERSION` в `.env` (тег `espocrm/espocrm:<версия>-apache`) →
  `make deploy`. При старте entrypoint сам делает `migrate`. Сначала прогнать тесты с новой
  версией: `docker-compose.test.yml` собирает образ с версией по умолчанию из `deploy/espocrm/Dockerfile`.
- Правки из админки (Entity Manager, Layout Manager) хранятся в томе `espocrm_custom`
  (`custom/Espo/Custom`) и переживают пересборку. Их раскладки перекрывают раскладки модуля.
  То, что нужно воспроизводимо, переносить в модуль.

Валюта по умолчанию — USD: `ESPOCRM_DEFAULT_CURRENCY=PLN` без PLN в `currencyList` ломает
`rebuild` (деление на ноль в курсах). PLN включают в админке: Administration → Currency.

WebSocket включён (`ESPOCRM_CONFIG_USE_WEB_SOCKET`). Сервер — контейнер `espocrm-websocket`,
браузер ходит на `wss://crm.n3spark.io/ws`. Cron EspoCRM (уведомления, письма) работает в
`espocrm-daemon`.

О назначенной Задаче человеку сотрудник узнаёт из уведомления CRM и письма. Письмо EspoCRM
шлёт сама (Task по умолчанию в Administration → Notifications → «Email notifications upon
assignment»), но только с SMTP (Administration → Outbound Emails) и адресом у сотрудника.
В репо и `.env.example` SMTP не задан: его вводит Заказчик в админке.

### Meta

URL вебхука `https://n8n.n3spark.io/webhook/meta`, verify token — `META_VERIFY_TOKEN` из `.env`.
Messenger, Instagram Direct и WhatsApp приходят в этот вебхук, подпись одна — `META_APP_SECRET`
приложения. Заказчика находим по странице (`companies.messenger_page_id`), аккаунту Instagram
(`companies.instagram_account_id`, сид — `DEMO_INSTAGRAM_ACCOUNT_ID`) или номеру
(`companies.whatsapp_phone_number_id`, сид — `DEMO_WHATSAPP_PHONE_NUMBER_ID`).
Пошагово для Заказчика — [docs/meta-setup.md](docs/meta-setup.md) и
[docs/whatsapp-setup.md](docs/whatsapp-setup.md).

Instagram Direct идёт через Messenger Platform: аккаунт Instagram связан со страницей Facebook,
ответ уходит в тот же Send API `/me/messages` с токеном этой страницы (`INSTAGRAM_ACCESS_TOKEN`).
Правило 24 часов как у Messenger: позже — только ответ сотрудника с меткой `HUMAN_AGENT`, до 7 дней.

WhatsApp отвечает через Cloud API номера (`WHATSAPP_ACCESS_TOKEN`). В течение 24 часов с
последнего сообщения Клиента ответ уходит свободным текстом. Позже уходит шаблон `news_update`:
на pl, если Беседа на польском, иначе на en.

### Напоминания о Записи

`appointment-reminders` идёт по расписанию (`REMINDER_SCHEDULE_CRON`, по умолчанию раз в 5 минут) и
напоминает о Записях, поставленных Ассистентом: за 24 часа и за 2 часа, каждый срок один раз. Время
и статус Записи берутся из CRM: перенесённая сотрудником Запись напоминается по новому времени,
отменённая (`Not Held`) — не напоминается. Срок, наступивший раньше, чем Клиент записался, пропускается.
Не ушло (сбой WhatsApp или SMSAPI) — следующий запуск повторит через 5 минут, пока срок не прошёл.

Клиент из WhatsApp получает шаблон `appointment_reminder` (дата и время, pl или en). Messenger и
Instagram Автоматизации после 24 часов не пускают, поэтому Клиенту оттуда уходит SMS через SMSAPI
(`SMSAPI_TOKEN`, `SMSAPI_SENDER`) на телефон из Заявки, тоже на pl или en. Запустить сразу:
`curl -X POST https://n8n.n3spark.io/webhook/reminders -H "X-Retry-Secret: $RETRY_WEBHOOK_SECRET"`.

### Алерт «AI не отвечает»

AI не ответил дважды подряд — бот (`TELEGRAM_BOT_TOKEN`) пишет в группу разработчиков
`ALERT_TELEGRAM_CHAT_ID`: Заказчик, Клиент, последнее сообщение. Заказчик алерт не получает:
Заявки и Передачи человеку он видит в EspoCRM. Бот только шлёт сообщения, вебхука у него нет.

### Retry

`retry-leads` идёт по расписанию (`RETRY_SCHEDULE_CRON`, по умолчанию раз в 5 минут). Запустить
сразу: `curl -X POST https://n8n.n3spark.io/webhook/retry -H "X-Retry-Secret: $RETRY_WEBHOOK_SECRET"`
(пустой секрет — ручной запуск закрыт).

Алерт «AI не отвечает» retry дошлёт, если основной поток не отправил его за 2 минуты.
Сообщение буфера без отметки об обработке retry берёт, если его взяли в работу больше 5 минут назад:
основной поток с повторами вызова AI укладывается в две минуты.

### Отчёты владельцу

`owner-report` шлёт владельцу (`OWNER_REPORT_EMAIL`, от `SMTP_FROM`) письмо на польском: дневной
отчёт — за вчера (`REPORT_DAILY_CRON`, по умолчанию 7:00), недельный — за прошлую неделю
с понедельника по воскресенье (`REPORT_WEEKLY_CRON`, по умолчанию понедельник 7:00). Время —
по Варшаве (`GENERIC_TIMEZONE`). По строке на Канал и итог: Заявки (`Lead`) и Записи (`Meeting`),
созданные в CRM за период, и конверсия — Записи / Заявки. Канал — поле «Kanał» Заявки и Записи:
его ставит переходник CRM, сотрудник выбирает его сам для Заявки, принятой по телефону или лично;
без Канала — строка «Bez kanału». Отчёты EspoCRM (платный Advanced Pack) не нужны.

Письмо уходит через SMTP из `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURE`, `SMTP_USER`, `SMTP_PASSWORD`
(credentials SMTP собирает `scripts/n8n_credentials.py`, после правки — `make workflows`). CRM
не ответила — письма нет, ошибка в выполнениях n8n. Запустить сразу, например за другой день:

```bash
curl -X POST https://n8n.n3spark.io/webhook/owner-report -H "X-Report-Secret: $REPORT_WEBHOOK_SECRET" \
  -H 'Content-Type: application/json' -d '{"period": "weekly", "today": "2026-10-26"}'
```

`period` — `daily` или `weekly`, `today` (необязательно) — день, в который будто бы идёт запуск.

## Правка workflow

Workflow лежат в `n8n/workflows/` без секретов и данных прогонов, credentials ссылаются на
фиксированные id из `scripts/n8n_credentials.py`, внешние URL и ключи берутся из `$env.*`.

- Правка в UI тестового стенда: `STAND_KEEP=1 uv run pytest tests/test_meta_webhook.py`,
  открыть n8n стенда (владельца создать при первом входе), затем выгрузить все workflow в репо:
  ```
  uv run python -c "from scripts.n8n_sync import pull; from tests.stand import Stand; pull(Stand())"
  ```
- Правка на проде: `make workflows-export` — то же самое с прод-n8n.

Экспорт перезаписывает файлы по id workflow, оставляет только `id`, `name`, `active` (всегда
`false`: включает `publish:workflow`), `settings`, `nodes`, `connections` и отказывается писать,
если в JSON нашлось значение секрета из env n8n (`SECRET_ENV` в `scripts/n8n_sync.py`).
Проверено тестом `tests/test_n8n_sync.py`: экспорт со стенда байт в байт совпадает с репо.

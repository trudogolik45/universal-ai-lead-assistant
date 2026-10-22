# Universal AI Lead Assistant

AI-ассистент для входящих заявок малого бизнеса в Messenger: отвечает Клиенту по Базе знаний
Заказчика, собирает Заявку и доставляет её в Google-таблицу, Telegram и CRM-webhook.
Спека: issue #1, термины: `GLOSSARY.md`.

## Документы

| Документ | О чём |
|---|---|
| `GLOSSARY.md` | Термины: Заказчик, Клиент, Ассистент, Беседа, Заявка, Режим ответа, Передача человеку |
| [docs/deviations.md](docs/deviations.md) | Чем MVP отличается от ТЗ и почему |
| [docs/knowledge-base.md](docs/knowledge-base.md) | Как менять Базу знаний, обязательные поля, Режим ответа, модель AI; удаление данных Клиента |
| [docs/crm-webhook.md](docs/crm-webhook.md) | Подключение CRM через webhook, формат JSON, когда уходит |
| [docs/meta-setup.md](docs/meta-setup.md) | Для Заказчика: приложение Meta, страница, вебхук, токены |
| [docs/google-setup.md](docs/google-setup.md) | Для Заказчика: service account, JSON-ключ, доступ к таблице |
| [docs/test-results.md](docs/test-results.md) | Сценарии спеки → тесты → результат последнего прогона |

## Как устроено

n8n (workflow в `n8n/workflows/`) + Postgres в Supabase (схема в `supabase/migrations/`).

| Workflow | Вход | Что делает |
|---|---|---|
| `meta-webhook` | `POST /webhook/meta` | Подпись Meta → сообщения в буфер входящих (`inbox`, дубль по id сообщения отсекается) → 200 Meta → `process-inbox` |
| `process-inbox` | вызов из других workflow | Сообщение из буфера через `handle-message`; дошло до конца — помечается обработанным, упало — остаётся в буфере |
| `handle-message` | вызов из других workflow | Заказчик по странице → Сообщение в Беседу → OpenRouter → ответ Клиенту, Заявка, Передача человеку |
| `deliver-lead` | вызов из других workflow | Заявка в Google-таблицу, затем в CRM-webhook |
| `notify-lead` | вызов из других workflow | Уведомление о Заявке или Передаче человеку в группу Telegram |
| `ai-alert` | вызов из других workflow | Алерт «AI не отвечает» в группу Telegram |
| `telegram-callback` | `POST /webhook/telegram` | Кнопки «Вернуть ассистенту» и «Закрыть»; возврат с полной Заявкой доставляет и объявляет её |
| `retry-leads` | раз в 5 минут; `POST /webhook/retry` | Повтор необработанных сообщений буфера, дозапись недоставленных Заявок и алертов «AI не отвечает», закрытие Бесед после 7 дней тишины |

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
удаляют контейнеры. Внешние API (OpenRouter, Meta Graph, Telegram, Google Sheets, CRM) изображает
фейк-сервер `tests/fake_server.py` на хосте, n8n ходит в него через `host.docker.internal`.
Без Docker тесты пропускаются.

- `STAND_KEEP=1 uv run pytest` — оставить стенд после прогона (логи: `docker compose -p <проект>
  -f docker-compose.test.yml logs n8n`, порт n8n: `... port n8n 5678`).
- Имя compose-проекта — `COMPOSE_PROJECT_NAME`, по умолчанию своё на каждый checkout;
  порты хоста случайные, поэтому параллельные стенды не пересекаются.
- Настоящая Google-таблица (`tests/test_lead_delivery_google.py`): задать
  `GOOGLE_SERVICE_ACCOUNT_EMAIL`, `GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY` и
  `GOOGLE_SHEETS_TEST_SPREADSHEET_ID` (таблица расшарена на service account как Editor). Тест
  поднимает второй стенд, пишет Заявку на свой временный лист, читает её обратно и удаляет лист.
  Без этих переменных тест пропускается.

Какие сценарии покрыты и результат последнего прогона — [docs/test-results.md](docs/test-results.md).

## Деплой

n8n работает на VPS `n3-vps` в Docker за Caddy: `https://n8n.n3spark.io`.

```
интернет :443 → traefik (k3s, TLS passthrough по SNI) → Caddy :8443 (TLS, Let's Encrypt) → n8n 127.0.0.1:5678
```

Публичные 80/443 на VPS держит traefik из k3s, он обслуживает остальные `*.n3spark.io`.
Для `n8n.n3spark.io` он не расшифровывает TLS, а передаёт поток Caddy
(`deploy/traefik-passthrough.yaml`). Caddy получает сертификат через TLS-ALPN-01.
HTTP→HTTPS редиректит traefik. Порт 8443 снаружи закрыт ufw, n8n слушает только loopback.

Что нужно на ноутбуке: ssh-хост `n3-vps` в `~/.ssh/config`, `rsync`, `uv`, Docker (для `make check`).

1. Однократно создать `.env` на VPS (`~/uala/.env`) из `.env.example` со сгенерированным
   `N8N_ENCRYPTION_KEY`. Существующий файл команда не перезапишет:
   ```
   make env-init
   ```
2. Вписать секреты в `~/uala/.env` на VPS (`ssh n3-vps`, редактор). Все переменные из `.env`
   видны нодам n8n как `$env.*`.
3. Поднять или обновить стек:
   ```
   make deploy
   ```
   Команда валидирует конфиги (`make check`), копирует `deploy/` на VPS, применяет
   маршрут traefik и делает `docker compose pull && up -d`. `.env` на VPS не трогает.
4. Открыть `https://n8n.n3spark.io` и при первом входе создать владельца n8n.
5. Схема и демо-профили в Supabase (идемпотентно, повтор безопасен):
   ```
   DATABASE_URL=... uv run python -m scripts.migrate
   DATABASE_URL=... DEMO_MESSENGER_PAGE_ID=... TELEGRAM_CHAT_ID=... GOOGLE_SHEETS_SPREADSHEET_ID=... \
     uv run python -m scripts.seed
   ```
6. Залить workflow:
   ```
   make workflows
   ```
   `scripts/n8n_sync.py push` по ssh: credentials Postgres из `DATABASE_URL` в `~/uala/.env`
   (передаются через stdin, на диск ноутбука не пишутся), импорт всех `n8n/workflows/*.json`,
   `publish:workflow` каждого и перезапуск n8n — вебхуки регистрируются только при старте.
   Повторять после каждой правки workflow.
7. Вебхуки внешних сервисов — см. ниже: Meta и Telegram.

После правки `.env` на VPS — `make deploy` (n8n перечитает переменные при пересоздании).
Версии образов: `N8N_VERSION`, `CADDY_VERSION` в `.env`, по умолчанию из `deploy/docker-compose.yml`.

### Meta

URL вебхука `https://n8n.n3spark.io/webhook/meta`, verify token — `META_VERIFY_TOKEN` из `.env`.
Пошагово для Заказчика — [docs/meta-setup.md](docs/meta-setup.md).

### Telegram

Бот пишет в группу Заказчика (`companies.telegram_chat_id`) и принимает нажатия кнопок
через вебхук `https://n8n.n3spark.io/webhook/telegram`. Регистрация (на VPS, где лежат секреты):

```
ssh n3-vps
cd uala
TELEGRAM_BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2-)
TELEGRAM_WEBHOOK_SECRET=$(grep '^TELEGRAM_WEBHOOK_SECRET=' .env | cut -d= -f2-)
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d url=https://n8n.n3spark.io/webhook/telegram \
  -d secret_token="$TELEGRAM_WEBHOOK_SECRET" \
  -d 'allowed_updates=["callback_query"]'
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

`getWebhookInfo` должен показать этот URL и пустой `last_error_message`. Workflow
`telegram-callback` отвечает 401 на запрос без заголовка `X-Telegram-Bot-Api-Secret-Token`,
равного `TELEGRAM_WEBHOOK_SECRET`. У бота один вебхук: `setWebhook` заменяет прежний, поэтому
боту нужен свой токен, не общий с другим сервисом.

### Retry

`retry-leads` идёт по расписанию (`RETRY_SCHEDULE_CRON`, по умолчанию раз в 5 минут). Запустить
сразу: `curl -X POST https://n8n.n3spark.io/webhook/retry -H "X-Retry-Secret: $RETRY_WEBHOOK_SECRET"`
(пустой секрет — ручной запуск закрыт).

Retry берёт только то, что не менялось последние 2 минуты: свежее ещё доставляет основной поток.
Сообщение буфера без отметки об обработке retry берёт, если его взяли в работу больше 5 минут назад:
основной поток с повторами вызова AI укладывается в две минуты.
В таблицу дописываются только `qualified` Заявки; в Telegram — «Новая заявка» для `qualified`,
сводка Передачи человеку для `needs_human` и недошедшие алерты «AI не отвечает».

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

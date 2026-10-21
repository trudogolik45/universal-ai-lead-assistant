# Universal AI Lead Assistant

AI-ассистент для входящих заявок малого бизнеса в Messenger. Спека: issue #1,
термины: `GLOSSARY.md`, отличия от ТЗ: `docs/deviations.md`.

## Инструкции для заказчика

- [Meta (Messenger)](docs/meta-setup.md): приложение, страница, вебхук, токены.
- [Google (Sheets)](docs/google-setup.md): service account, JSON-ключ, доступ к таблице.

## Запуск на VPS

n8n работает на VPS `n3-vps` в Docker за Caddy: `https://n8n.n3spark.io`.

```
интернет :443 → traefik (k3s, TLS passthrough по SNI) → Caddy :8443 (TLS, Let's Encrypt) → n8n 127.0.0.1:5678
```

Публичные 80/443 на VPS держит traefik из k3s, он обслуживает остальные `*.n3spark.io`.
Для `n8n.n3spark.io` он не расшифровывает TLS, а передаёт поток Caddy
(`deploy/traefik-passthrough.yaml`). Caddy получает сертификат через TLS-ALPN-01.
HTTP→HTTPS редиректит traefik. Порт 8443 снаружи закрыт ufw, n8n слушает только loopback.

Что нужно на ноутбуке: ssh-хост `n3-vps` в `~/.ssh/config`, `rsync`, Docker (для `make check`).

1. Однократно создать `.env` на VPS (`~/uala/.env`) из `.env.example` со сгенерированным
   `N8N_ENCRYPTION_KEY`. Существующий файл команда не перезапишет:
   ```
   make env-init
   ```
2. Вписать секреты в `~/uala/.env` на VPS (`ssh n3-vps`, редактор). Имена всех переменных
   и их назначение — в `.env.example`. Все переменные из `.env` видны нодам n8n как `$env.*`.
3. Поднять или обновить стек:
   ```
   make deploy
   ```
   Команда валидирует конфиги (`make check`), копирует `deploy/` на VPS, применяет
   маршрут traefik и делает `docker compose pull && up -d`. `.env` на VPS не трогает.
4. Открыть `https://n8n.n3spark.io` и при первом входе создать владельца n8n.

После правки `.env` на VPS — `make deploy` (n8n перечитает переменные при пересоздании).
Версии образов: `N8N_VERSION`, `CADDY_VERSION` в `.env`, по умолчанию из `deploy/docker-compose.yml`.

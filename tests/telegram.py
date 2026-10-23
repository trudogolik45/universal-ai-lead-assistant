"""Telegram в тестах: что бот отправил в группу разработчиков (алерт «AI не отвечает»)."""

from tests.fake_server import Response

# Значения из docker-compose.test.yml. Путь Bot API — /bot<token>/<method>.
BOT_TOKEN = "test-telegram-token"
SEND_MESSAGE_PATH = f"/telegram/bot{BOT_TOKEN}/sendMessage"
ALERT_CHAT_ID = "-1009990000000"


def sent_to_telegram(fake) -> list[dict]:
    """Тела sendMessage по порядку."""
    return [request.json() for request in fake.requests(SEND_MESSAGE_PATH)]


def telegram_fails(fake):
    """Bot API отвечает ошибкой на sendMessage (как при неверном chat_id)."""
    fake.respond("POST", SEND_MESSAGE_PATH, Response(400, {"ok": False, "description": "Bad Request"}))

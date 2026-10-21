"""Фейковый Telegram Bot API: что бот отправил в группу Заказчика."""

from tests.fake_server import Response

# Токен бота из docker-compose.test.yml: путь Bot API — /bot<token>/<method>.
BOT_TOKEN = "test-telegram-token"
SEND_MESSAGE_PATH = f"/telegram/bot{BOT_TOKEN}/sendMessage"


def sent_to_telegram(fake) -> list[dict]:
    """Тела sendMessage по порядку."""
    return [request.json() for request in fake.requests(SEND_MESSAGE_PATH)]


def callback_data(message: dict) -> list[str]:
    """callback_data всех inline-кнопок сообщения."""
    keyboard = message.get("reply_markup", {}).get("inline_keyboard", [])
    return [button["callback_data"] for row in keyboard for button in row]


def telegram_fails(fake):
    """Bot API отвечает ошибкой на sendMessage (как при неверном chat_id)."""
    fake.respond("POST", SEND_MESSAGE_PATH, Response(400, {"ok": False, "description": "Bad Request"}))

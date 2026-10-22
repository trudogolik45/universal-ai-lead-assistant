"""Telegram в тестах: что бот отправил в группу Заказчика и нажатия кнопок в вебхук n8n."""

import time
import uuid

import httpx

from tests.fake_server import Response

# Значения из docker-compose.test.yml. Путь Bot API — /bot<token>/<method>.
BOT_TOKEN = "test-telegram-token"
SEND_MESSAGE_PATH = f"/telegram/bot{BOT_TOKEN}/sendMessage"
ANSWER_CALLBACK_PATH = f"/telegram/bot{BOT_TOKEN}/answerCallbackQuery"
# Telegram шлёт секрет вебхука в заголовке X-Telegram-Bot-Api-Secret-Token.
WEBHOOK_SECRET = "test-telegram-webhook-secret"
WEBHOOK_PATH = "/webhook/telegram"


def sent_to_telegram(fake) -> list[dict]:
    """Тела sendMessage по порядку."""
    return [request.json() for request in fake.requests(SEND_MESSAGE_PATH)]


def answered_callbacks(fake) -> list[dict]:
    """Тела answerCallbackQuery по порядку."""
    return [request.json() for request in fake.requests(ANSWER_CALLBACK_PATH)]


def callback_data(message: dict) -> list[str]:
    """callback_data всех inline-кнопок сообщения."""
    keyboard = message.get("reply_markup", {}).get("inline_keyboard", [])
    return [button["callback_data"] for row in keyboard for button in row]


def telegram_fails(fake):
    """Bot API отвечает ошибкой на sendMessage (как при неверном chat_id)."""
    fake.respond("POST", SEND_MESSAGE_PATH, Response(400, {"ok": False, "description": "Bad Request"}))


class TelegramClient:
    """Шлёт в вебхук n8n то, что прислал бы Telegram при нажатии inline-кнопки."""

    def __init__(self, n8n_url: str):
        self.url = n8n_url + WEBHOOK_PATH

    def press(self, data: str, chat_id: str, secret: str = WEBHOOK_SECRET) -> httpx.Response:
        update = {
            "update_id": int(time.time() * 1000),
            "callback_query": {
                "id": f"cb-{uuid.uuid4().hex[:8]}",
                "from": {"id": 42, "is_bot": False, "first_name": "Owner"},
                "data": data,
                "message": {"message_id": 1, "chat": {"id": int(chat_id), "type": "supergroup"}},
            },
        }
        headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
        return httpx.post(self.url, json=update, headers=headers, timeout=10)

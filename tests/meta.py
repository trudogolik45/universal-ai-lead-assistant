"""Клиент Meta для тестов: шлёт в вебхук n8n то, что прислала бы Meta."""

import hashlib
import hmac
import json
import time
import uuid

import httpx

# Значения из docker-compose.test.yml.
APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
WEBHOOK_PATH = "/webhook/meta"


def sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def new_mid() -> str:
    return f"m_{uuid.uuid4().hex}"


def messenger_payload(page_id: str, sender_id: str, text: str, mid: str | None = None) -> dict:
    """Вебхук Messenger с одним текстовым сообщением Клиента."""
    now = int(time.time() * 1000)
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "time": now,
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": page_id},
                        "timestamp": now,
                        "message": {"mid": mid or new_mid(), "text": text},
                    }
                ],
            }
        ],
    }


def new_wamid() -> str:
    return f"wamid.{uuid.uuid4().hex}"


def whatsapp_payload(phone_number_id: str, wa_id: str, text: str, wamid: str | None = None) -> dict:
    """Вебхук WhatsApp Cloud API с одним текстовым сообщением Клиента на номер phone_number_id."""
    return whatsapp_change(phone_number_id, {
        "contacts": [{"profile": {"name": "Klient"}, "wa_id": wa_id}],
        "messages": [{
            "from": wa_id,
            "id": wamid or new_wamid(),
            "timestamp": str(int(time.time())),
            "type": "text",
            "text": {"body": text},
        }],
    })


def whatsapp_status_payload(phone_number_id: str, wa_id: str) -> dict:
    """Вебхук WhatsApp о доставке исходящего: сообщения Клиента в нём нет."""
    return whatsapp_change(phone_number_id, {
        "statuses": [{
            "id": new_wamid(),
            "recipient_id": wa_id,
            "status": "delivered",
            "timestamp": str(int(time.time())),
        }],
    })


def whatsapp_change(phone_number_id: str, value: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "48500100200", "phone_number_id": phone_number_id},
                    **value,
                },
            }],
        }],
    }


class MetaClient:
    def __init__(self, n8n_url: str):
        self.url = n8n_url + WEBHOOK_PATH

    def post(self, payload: dict, signature: str | None = None) -> httpx.Response:
        # Как Meta: ASCII-JSON с \uXXXX. Подпись считается по этим байтам.
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature if signature is not None else sign(body),
        }
        return httpx.post(self.url, content=body, headers=headers, timeout=10)

    def verify(self, token: str, challenge: str) -> httpx.Response:
        params = {"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": challenge}
        return httpx.get(self.url, params=params, timeout=10)

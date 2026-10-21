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

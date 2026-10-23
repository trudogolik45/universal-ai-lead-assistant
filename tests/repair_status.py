"""Смена статуса Заказ-наряда в EspoCRM: хук модуля Uala зовёт webhook n8n (контракт — tests/test_espocrm.py)."""

import uuid

import httpx

from tests.espocrm import EMPLOYEE_REPLY_SECRET


def change_status(n8n_url, status, conversations, secret=EMPLOYEE_REPLY_SECRET) -> httpx.Response:
    """Вызов, который делает хук EspoCRM, когда мастер меняет статус Заказ-наряда:
    conversations — Беседы Клиента в CRM, [{channel, sender_id}]."""
    return httpx.post(
        f"{n8n_url}/webhook/repair-status",
        headers={"X-Uala-Secret": secret},
        json={"crm_repair_order_id": uuid.uuid4().hex[:17], "status": status, "conversations": conversations},
        timeout=10,
    )

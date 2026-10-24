"""Смета (workflow estimates): вызов хука EspoCRM при смене статуса Сметы (контракт — tests/test_espocrm.py)
и ручной запуск цепочки уточнений — тест не ждёт расписания, а дёргает вебхук /webhook/estimates с секретом retry."""

import uuid

import httpx

from tests.espocrm import N8N_HOOK_SECRET
from tests.retry import RETRY_SECRET


def change_estimate_status(
    n8n_url, status, conversations, estimate_id=None, order_id=None, name="Wymiana sprzęgła",
    amount=1250.5, currency="PLN", secret=N8N_HOOK_SECRET,
) -> httpx.Response:
    """Вызов, который делает хук EspoCRM, когда сотрудник меняет статус Сметы:
    conversations — Беседы Клиента Заказ-наряда в CRM, [{channel, sender_id}]."""
    return httpx.post(
        f"{n8n_url}/webhook/estimate",
        headers={"X-Uala-Secret": secret},
        json={
            "crm_estimate_id": estimate_id or uuid.uuid4().hex[:17],
            "crm_repair_order_id": order_id or uuid.uuid4().hex[:17],
            "name": name,
            "status": status,
            "amount": amount,
            "currency": currency,
            "conversations": conversations,
        },
        timeout=10,
    )


def run_estimates(n8n_url, secret=RETRY_SECRET) -> httpx.Response:
    return httpx.post(f"{n8n_url}/webhook/estimates", headers={"X-Retry-Secret": secret}, timeout=10)

"""Закрытие Задачи человеку в EspoCRM: хук модуля Uala зовёт webhook n8n (контракт — tests/test_espocrm.py)."""

import httpx

from tests.espocrm import N8N_HOOK_SECRET


def complete_task(n8n_url, crm_task_id, secret=N8N_HOOK_SECRET) -> httpx.Response:
    """Вызов, который делает хук EspoCRM, когда сотрудник закрывает Задачу."""
    return httpx.post(
        f"{n8n_url}/webhook/task-done",
        headers={"X-Uala-Secret": secret},
        json={"crm_task_id": crm_task_id},
        timeout=10,
    )

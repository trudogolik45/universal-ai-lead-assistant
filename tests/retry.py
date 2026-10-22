"""Ручной запуск workflow retry-leads: тест не ждёт расписания, а дёргает вебхук /webhook/retry."""

import httpx

# Значение из docker-compose.test.yml.
RETRY_SECRET = "test-retry-secret"


def run_retry(n8n_url, secret=RETRY_SECRET) -> httpx.Response:
    return httpx.post(f"{n8n_url}/webhook/retry", headers={"X-Retry-Secret": secret}, timeout=10)

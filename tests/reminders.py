"""Напоминания о Записи (workflow appointment-reminders): ручной запуск и что ушло Клиенту.

Тест не ждёт расписания: тот же workflow запускает вебхук /webhook/reminders с секретом retry.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx

from tests.retry import RETRY_SECRET

# Значение из docker-compose.test.yml.
SMSAPI_TOKEN = "test-smsapi-token"
SMS_PATH = "/smsapi/sms.do"
REMINDER_TEMPLATE = "appointment_reminder"


def run_reminders(n8n_url, secret=RETRY_SECRET) -> httpx.Response:
    return httpx.post(f"{n8n_url}/webhook/reminders", headers={"X-Retry-Secret": secret}, timeout=10)


def espo_time(moment: datetime) -> str:
    """Дата EspoCRM: UTC до секунды."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def in_hours(hours: float) -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)


def sms_sent(fake) -> list[dict]:
    """SMS, отправленные через SMSAPI: поля формы и заголовок Authorization."""
    return [
        {**{k: v[0] for k, v in parse_qs(r.body.decode()).items()}, "authorization": r.headers.get("authorization")}
        for r in fake.requests(SMS_PATH)
    ]


def planned_where(after: str, before: str) -> list[dict]:
    """Условие переходника CRM «Записи к напоминанию»: запланированные с началом в окне; отменённые
    (Not Held) и прошедшие (Held) не напоминаются."""
    return [
        {"type": "equals", "attribute": "status", "value": "Planned"},
        {"type": "greaterThan", "attribute": "dateStart", "value": after},
        {"type": "lessThan", "attribute": "dateStart", "value": before},
    ]

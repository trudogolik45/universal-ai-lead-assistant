"""Отчёт владельцу: ручной запуск workflow owner-report и условие, которым переходник CRM считает
Заявки и Записи Канала за период."""

import httpx

# Значение из docker-compose.test.yml.
REPORT_SECRET = "test-report-secret"


def run_report(n8n_url, period: str, today: str | None = None, secret: str = REPORT_SECRET) -> httpx.Response:
    """Ручной запуск вместо расписания: отчёт за период перед днём today (YYYY-MM-DD, по Варшаве)."""
    body = {"period": period, **({"today": today} if today else {})}
    return httpx.post(f"{n8n_url}/webhook/owner-report", headers={"X-Report-Secret": secret}, json=body, timeout=10)


def report_where(starts_at: str, ends_at: str, channel: str) -> list[dict]:
    """Условие переходника CRM: создано в периоде [starts_at, ends_at) — даты EspoCRM в UTC — в Канале."""
    return [
        {"type": "greaterThanOrEquals", "attribute": "createdAt", "value": starts_at},
        {"type": "lessThan", "attribute": "createdAt", "value": ends_at},
        {"type": "equals", "attribute": "channel", "value": channel},
    ]

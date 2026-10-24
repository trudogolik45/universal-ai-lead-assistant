"""Напоминания о ТО и сезонной замене шин (workflow marketing-reminders): ручной запуск и условия,
которыми переходник CRM ищет Клиентов с Согласием на рекламу.

Тест не ждёт расписания: тот же workflow запускает вебхук /webhook/marketing с секретом retry.
"""

import httpx

from tests.retry import RETRY_SECRET

# Вопрос о Согласии на рекламу, который Ассистент один раз добавляет к ответу (узел «Build prompt»).
CONSENT_QUESTION = {
    "pl": "Czy chcesz otrzymywać od nas przypomnienia o przeglądzie i sezonowej wymianie opon? Odpowiedz „tak” lub „nie”.",
    "en": "Would you like to receive reminders from us about car service and seasonal tyre changes? Please reply yes or no.",
}
# Одобренные у Meta шаблоны WhatsApp (docs/whatsapp-setup.md).
SERVICE_TEMPLATE = "service_reminder"
WINTER_TYRES_TEMPLATE = "winter_tyres_reminder"
SUMMER_TYRES_TEMPLATE = "summer_tyres_reminder"


def run_marketing(n8n_url, today: str | None = None, secret: str = RETRY_SECRET) -> httpx.Response:
    """Ручной запуск вместо расписания: рассылка на день today (YYYY-MM-DD, по Варшаве)."""
    body = {"today": today} if today else {}
    return httpx.post(f"{n8n_url}/webhook/marketing", headers={"X-Retry-Secret": secret}, json=body, timeout=10)


def consented_where() -> list[dict]:
    """Условие переходника CRM: Клиенты (Contact), согласные на рекламу."""
    return [{"type": "isTrue", "attribute": "marketingConsent"}]


def conversations_of_where(contact_ids: list[str]) -> list[dict]:
    """Условие переходника CRM: Беседы этих Клиентов — по ним Канал и id Клиента в нём."""
    return [{"type": "in", "attribute": "contactId", "value": contact_ids}]

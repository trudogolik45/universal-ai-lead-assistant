"""Ответы фейкового OpenRouter для тестов Ассистента."""

import json

from tests.fake_server import Response

COMPLETIONS_PATH = "/openrouter/chat/completions"

LEAD_FIELDS = (
    "name", "phone", "contact", "vehicle_brand", "vehicle_model", "service", "description", "desired_date",
)


def assistant_reply(
    reply: str = "Dzień dobry!",
    language: str | None = "pl",
    intent: str = "other",
    lead_data: dict | None = None,
    missing_fields: list[str] | None = None,
    qualified: bool = False,
    needs_human: bool = False,
    handoff_reason: str | None = None,
    appointment_start: str | None = None,
    marketing_consent: bool | None = None,
) -> Response:
    """Ответ chat/completions, в content — JSON по схеме Ассистента. Неуказанные поля Заявки — null.
    appointment_start — слот, в который Ассистент записывает Клиента (местное время «YYYY-MM-DD HH:MM»).
    marketing_consent — ответ Клиента на вопрос о Согласии на рекламу: True, False или None (не отвечал)."""
    content = {
        "reply": reply,
        "language": language,
        "intent": intent,
        "lead_data": {field: (lead_data or {}).get(field) for field in LEAD_FIELDS},
        "missing_fields": missing_fields or [],
        "qualified": qualified,
        "needs_human": needs_human,
        "handoff_reason": handoff_reason,
        "appointment_start": appointment_start,
        "marketing_consent": marketing_consent,
    }
    return raw_reply(json.dumps(content))


def raw_reply(content: str) -> Response:
    """Ответ chat/completions с произвольным content (например, не по схеме)."""
    return Response(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})


def respond_with(fake, *responses: Response):
    """Ответы OpenRouter по очереди: по одному на входящее Сообщение, последний повторяется."""
    fake.respond("POST", COMPLETIONS_PATH, *responses)


def completion_requests(fake) -> list[dict]:
    return [request.json() for request in fake.requests(COMPLETIONS_PATH)]

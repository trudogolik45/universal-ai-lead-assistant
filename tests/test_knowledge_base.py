"""База знаний из EspoCRM: Ассистент читает её на каждое Сообщение (#23).

Главный шов: подписанный webhook Meta на входе, на выходе — запросы в фейковые EspoCRM и OpenRouter.
"""

import uuid

import pytest

from tests import knowledge
from tests.factories import create_company
from tests.fake_server import Response
from tests.knowledge import knowledge_item, knowledge_requests
from tests.meta import MetaClient, messenger_payload
from tests.openrouter import assistant_reply, completion_requests, respond_with
from tests.polling import eventually, stays

PAGE_ID = "page-230"
OIL_CHANGE = "Wymiana oleju silnikowego i filtra oleju"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "AutoPro Service")
    db.execute("update companies set messenger_page_id = %s where id = %s", (PAGE_ID, company_id))
    return company_id


@pytest.fixture
def client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


def oil_change(price: float) -> dict:
    return knowledge_item(OIL_CHANGE, description="Bez kosztu oleju i filtra. 45–60 min.", price=price, price_from=True)


def system_prompts(fake) -> list[str]:
    return [request["messages"][0]["content"] for request in completion_requests(fake)]


def sent_texts(fake) -> list[str]:
    return [request.json()["message"]["text"] for request in fake.requests("/meta/me/messages")]


def unprocessed_inbox(db) -> int:
    """Необработанные сообщения буфера: их повторит retry (tests/test_inbox.py)."""
    return db.execute("select count(*) from inbox where processed_at is null").fetchone()[0]


def test_assistant_answers_price_question_from_crm_knowledge_base(db, fake, meta, client):
    knowledge.respond_with(fake, [
        oil_change(120),
        knowledge_item("Godziny pracy", kind="hours", description="Pn–pt 8:00–18:00, sb 9:00–14:00."),
        knowledge_item("Adres", kind="company", description="ul. Warsztatowa 12, 40-001 Katowice"),
    ])
    respond_with(fake, assistant_reply(reply="Wymiana oleju kosztuje od 120 zł, bez oleju i filtra.", intent="price"))

    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje wymiana oleju?"))

    eventually(lambda: sent_texts(fake))
    assert sent_texts(fake) == ["Wymiana oleju kosztuje od 120 zł, bez oleju i filtra."]
    system = system_prompts(fake)[0]
    for fact in (OIL_CHANGE, '"price":120', '"priceFrom":true', "Pn–pt 8:00–18:00", "ul. Warsztatowa 12"):
        assert fact in system
    headers = {name.lower(): value for name, value in knowledge_requests(fake)[0].headers.items()}
    assert headers["x-api-key"] == "test-espocrm-key"


def test_price_changed_in_crm_reaches_the_next_reply(db, fake, meta, client):
    knowledge.respond_with(fake, [oil_change(120)], [oil_change(150)])
    respond_with(fake, assistant_reply(reply="Od 120 zł."), assistant_reply(reply="Od 150 zł."))
    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje wymiana oleju?"))
    eventually(lambda: sent_texts(fake))

    meta.post(messenger_payload(PAGE_ID, client, "A teraz ile?"))

    eventually(lambda: len(sent_texts(fake)) == 2)
    first, second = system_prompts(fake)
    assert '"price":120' in first
    assert '"price":150' in second
    assert '"price":120' not in second


def test_without_crm_knowledge_base_assistant_does_not_guess_and_message_waits_in_buffer(db, fake, meta, client):
    knowledge.respond_with(fake, Response(500, {}))
    respond_with(fake, assistant_reply(reply="Od 1 zł."))

    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje wymiana oleju?"))

    eventually(lambda: len(knowledge_requests(fake)) == 2)
    stays(lambda: not completion_requests(fake) and not sent_texts(fake))
    assert unprocessed_inbox(db) == 1

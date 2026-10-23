"""Канал WhatsApp Cloud API: подписанный вебхук Meta проходит Приём, Ассистент отвечает через
Cloud API номера Заказчика. Внутри 24 часов с последнего сообщения Клиента — свободный текст,
позже — только одобренный шаблон на pl или en."""

import uuid

import pytest

from tests import knowledge
from tests.factories import create_company
from tests.fake_server import Response
from tests.knowledge import KNOWLEDGE_PATH
from tests.meta import MetaClient, new_wamid, sign, whatsapp_payload, whatsapp_status_payload
from tests.openrouter import assistant_reply, respond_with
from tests.polling import eventually, stays
from tests.retry import run_retry

PHONE_NUMBER_ID = "pnid-100"
SEND_PATH = f"/meta/{PHONE_NUMBER_ID}/messages"
# Значение из docker-compose.test.yml.
ACCESS_TOKEN = "test-whatsapp-token"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "WhatsApp Co")
    db.execute("update companies set whatsapp_phone_number_id = %s where id = %s", (PHONE_NUMBER_ID, company_id))
    return company_id


@pytest.fixture
def client(db, company):
    """Номер Клиента в WhatsApp (wa_id). Его данные стираются через delete_client после теста."""
    wa_id = "48" + str(uuid.uuid4().int)[:9]
    yield wa_id
    db.execute("select delete_client(%s, 'whatsapp', %s)", (company, wa_id))


def saved_messages(db, wamid):
    return db.execute(
        "select m.direction, m.text, v.channel, v.sender_id"
        " from messages m join conversations v on v.id = m.conversation_id"
        " where m.provider_message_id = %s",
        (wamid,),
    ).fetchall()


def sent(fake):
    return fake.requests(SEND_PATH)


def test_client_message_is_saved_and_answered_with_free_text(db, fake, meta, client):
    respond_with(fake, assistant_reply(reply="Dzień dobry! W czym pomóc?"))
    wamid = new_wamid()

    response = meta.post(whatsapp_payload(PHONE_NUMBER_ID, client, "Dzień dobry, ile kosztuje wymiana oleju?", wamid))

    assert response.status_code == 200
    request = eventually(lambda: sent(fake))[0]
    assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert request.json() == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": client,
        "type": "text",
        "text": {"body": "Dzień dobry! W czym pomóc?"},
    }
    assert saved_messages(db, wamid) == [("in", "Dzień dobry, ile kosztuje wymiana oleju?", "whatsapp", client)]


def test_wrong_signature_is_rejected_and_nothing_saved(db, fake, meta, client):
    payload = whatsapp_payload(PHONE_NUMBER_ID, client, "Fałszywka")

    response = meta.post(payload, signature=sign(b"other body"))

    assert response.status_code == 401
    stays(lambda: message_count(db) == 0)
    assert sent(fake) == []


def test_delivery_status_is_acknowledged_and_ignored(db, fake, meta, client):
    response = meta.post(whatsapp_status_payload(PHONE_NUMBER_ID, client))

    assert response.status_code == 200
    stays(lambda: message_count(db) == 0)
    assert fake.requests("/openrouter") == []


def test_repeated_webhook_gets_one_reply(fake, meta, client):
    respond_with(fake, assistant_reply())
    payload = whatsapp_payload(PHONE_NUMBER_ID, client, "Dzień dobry", new_wamid())

    meta.post(payload)
    meta.post(payload)

    eventually(lambda: sent(fake))
    stays(lambda: len(sent(fake)) == 1)


@pytest.mark.parametrize(("client_language", "template_language"), [("pl", "pl"), ("de", "en")])
def test_reply_after_24_hours_goes_as_approved_template(
    db, fake, meta, n8n_url, client, client_language, template_language
):
    respond_with(fake, assistant_reply(reply="Odpowiedź po czasie", language=client_language))
    knowledge.respond_with(fake, Response(500, {}))
    wamid = new_wamid()
    meta.post(whatsapp_payload(PHONE_NUMBER_ID, client, "Dzień dobry", wamid))
    eventually(lambda: saved_messages(db, wamid) and len(fake.requests(KNOWLEDGE_PATH)) == 2)

    client_wrote_hours_ago(db, wamid, hours=25)
    knowledge.respond_with(fake, [])
    db.execute("update inbox set claimed_at = now() - interval '10 minutes'")
    run_retry(n8n_url)

    assert eventually(lambda: sent(fake))[0].json() == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": client,
        "type": "template",
        "template": {"name": "news_update", "language": {"code": template_language}},
    }


def message_count(db):
    return db.execute("select count(*) from messages").fetchone()[0]


def client_wrote_hours_ago(db, wamid, hours):
    db.execute(
        "update messages set created_at = now() - make_interval(hours => %s) where provider_message_id = %s",
        (hours, wamid),
    )

import uuid

import pytest

from tests.factories import create_company
from tests.fake_server import Response
from tests.meta import MetaClient, messenger_payload
from tests.openrouter import assistant_reply, respond_with
from tests.polling import eventually, stays
from tests.telegram import callback_data, sent_to_telegram, telegram_fails

PAGE_ID = "page-700"
SEND_API_PATH = "/meta/me/messages"
CHAT_ID = "-1001234567890"
FULL_LEAD = {
    "name": "Anna Kowalska",
    "contact": "+48 600 100 200",
    "service": "Montaż mebli",
    "description": "Szafa z IKEA",
    "desired_date": "piątek rano",
}


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Telegram Co")
    db.execute(
        "update companies set messenger_page_id = %s, telegram_chat_id = %s where id = %s",
        (PAGE_ID, CHAT_ID, company_id),
    )
    return company_id


@pytest.fixture
def client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


def telegram_sent_lead_id(db):
    """id Заявки с заполненным telegram_sent_at или None."""
    row = db.execute("select id from leads where telegram_sent_at is not null").fetchone()
    return row and row[0]


def marked_for_ai_alert(db):
    return db.execute("select count(*) from messages where ai_failed_at is not null").fetchone()[0]


def sent_messages(fake):
    return fake.requests(SEND_API_PATH)


def qualified_reply():
    return assistant_reply(intent="booking", lead_data=FULL_LEAD, qualified=True)


def test_qualified_lead_is_announced_in_customer_group_with_close_button(db, fake, meta, client):
    respond_with(fake, qualified_reply())

    meta.post(messenger_payload(PAGE_ID, client, "Anna, +48 600 100 200, szafa z IKEA w piątek rano"))

    message = eventually(lambda: sent_to_telegram(fake))[0]
    lead_id = eventually(lambda: telegram_sent_lead_id(db))
    assert message["chat_id"] == CHAT_ID
    for expected in ("Telegram Co", client, "booking", *FULL_LEAD.values()):
        assert expected in message["text"]
    assert callback_data(message) == [f"close:{lead_id}"]


def test_lead_qualified_again_is_not_announced_twice(db, fake, meta, client):
    respond_with(fake, qualified_reply())

    meta.post(messenger_payload(PAGE_ID, client, "Anna, +48 600 100 200, szafa z IKEA w piątek rano"))
    eventually(lambda: telegram_sent_lead_id(db))
    meta.post(messenger_payload(PAGE_ID, client, "Dziękuję!"))

    eventually(lambda: len(sent_messages(fake)) == 2)
    stays(lambda: len(sent_to_telegram(fake)) == 1)


def test_failed_telegram_delivery_leaves_lead_unsent_and_client_answered(db, fake, meta, client):
    respond_with(fake, qualified_reply())
    telegram_fails(fake)

    meta.post(messenger_payload(PAGE_ID, client, "Anna, +48 600 100 200, szafa z IKEA w piątek rano"))

    eventually(lambda: sent_to_telegram(fake) and sent_messages(fake))
    stays(lambda: telegram_sent_lead_id(db) is None)


def test_two_failed_ai_calls_alert_customer_group_with_last_message(db, fake, meta, client):
    respond_with(fake, Response(500, {}))

    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje montaż?"))

    alert = eventually(lambda: sent_to_telegram(fake))[0]
    assert alert["chat_id"] == CHAT_ID
    for expected in ("Telegram Co", client, "Ile kosztuje montaż?"):
        assert expected in alert["text"]
    stays(lambda: len(sent_to_telegram(fake)) == 1)


def test_company_without_telegram_group_gets_no_ai_alert(db, fake, meta, client, company):
    db.execute("update companies set telegram_chat_id = null where id = %s", (company,))
    respond_with(fake, Response(500, {}))

    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje montaż?"))

    eventually(lambda: marked_for_ai_alert(db))
    stays(lambda: not sent_to_telegram(fake))

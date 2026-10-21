import uuid

import pytest

from tests.factories import create_company
from tests.meta import VERIFY_TOKEN, MetaClient, messenger_payload, new_mid, sign
from tests.polling import eventually, stays

PAGE_ID = "page-100"


@pytest.fixture
def meta(n8n_url, fake):
    """Фейк сброшен: OpenRouter без ответов, поэтому Заявка остаётся new."""
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Webhook Co")
    db.execute("update companies set messenger_page_id = %s where id = %s", (PAGE_ID, company_id))
    return company_id


@pytest.fixture
def client(db, company):
    """Клиент страницы PAGE_ID. Его данные стираются через delete_client после теста."""
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


def saved_messages(db, mid):
    return db.execute(
        "select m.direction, m.text, v.channel, v.sender_id, v.status, l.status"
        " from messages m"
        " join conversations v on v.id = m.conversation_id"
        " join leads l on l.conversation_id = v.id"
        " where m.provider_message_id = %s",
        (mid,),
    ).fetchall()


def message_count(db):
    return db.execute("select count(*) from messages").fetchone()[0]


def test_verification_with_right_token_returns_challenge(meta):
    response = meta.verify(VERIFY_TOKEN, "challenge-123")

    assert response.status_code == 200
    assert response.text == "challenge-123"


def test_verification_with_wrong_token_is_forbidden(meta):
    response = meta.verify("wrong-token", "challenge-123")

    assert response.status_code == 403
    assert "challenge-123" not in response.text


def test_message_is_saved_with_new_conversation_and_lead(db, meta, client):
    mid = new_mid()

    response = meta.post(messenger_payload(PAGE_ID, client, "Dzień dobry, ile kosztuje montaż?", mid))

    assert response.status_code == 200
    assert eventually(lambda: saved_messages(db, mid)) == [
        ("in", "Dzień dobry, ile kosztuje montaż?", "messenger", client, "open", "new")
    ]


def test_wrong_signature_is_rejected_and_nothing_saved(db, meta, client):
    payload = messenger_payload(PAGE_ID, client, "Fałszywka")

    response = meta.post(payload, signature=sign(b"other body"))

    assert response.status_code == 401
    stays(lambda: message_count(db) == 0)


def test_missing_signature_is_rejected(db, meta, client):
    response = meta.post(messenger_payload(PAGE_ID, client, "Bez podpisu"), signature="")

    assert response.status_code == 401
    stays(lambda: message_count(db) == 0)


def test_repeated_webhook_does_not_duplicate_message(db, meta, client):
    payload = messenger_payload(PAGE_ID, client, "Powtórka", new_mid())
    meta.post(payload)
    eventually(lambda: message_count(db) == 1)

    response = meta.post(payload)

    assert response.status_code == 200
    stays(lambda: message_count(db) == 1)


def test_next_message_continues_same_conversation(db, meta, client, company):
    meta.post(messenger_payload(PAGE_ID, client, "Pierwsza"))
    eventually(lambda: message_count(db) == 1)

    meta.post(messenger_payload(PAGE_ID, client, "Druga"))

    eventually(lambda: message_count(db) == 2)
    conversations, leads = db.execute(
        "select (select count(*) from conversations), (select count(*) from leads)"
    ).fetchone()
    assert (conversations, leads) == (1, 1)


def test_message_for_unknown_page_is_ignored(db, meta, client, company):
    response = meta.post(messenger_payload("unknown-page", client, "Halo?"))

    assert response.status_code == 200
    stays(lambda: message_count(db) == 0)


def test_page_echo_is_not_saved_as_client_message(db, meta, client, company):
    payload = messenger_payload(PAGE_ID, client, "Odpowiedź strony")
    payload["entry"][0]["messaging"][0]["message"]["is_echo"] = True

    response = meta.post(payload)

    assert response.status_code == 200
    stays(lambda: message_count(db) == 0)

"""Канал Instagram Direct: подписанный вебхук Meta проходит Приём, Ассистент отвечает через
Send API Instagram (Messenger Platform, токен страницы, связанной с аккаунтом Instagram)."""

import uuid

import pytest

from tests.factories import create_company
from tests.meta import MetaClient, instagram_echo_payload, instagram_payload, new_mid, sign
from tests.openrouter import assistant_reply, respond_with
from tests.polling import eventually, stays
from tests.test_employee_reply import employee_reply

ACCOUNT_ID = "ig-100"
SEND_PATH = "/meta/me/messages"
# Значение из docker-compose.test.yml.
ACCESS_TOKEN = "test-instagram-token"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Instagram Co")
    db.execute("update companies set instagram_account_id = %s where id = %s", (ACCOUNT_ID, company_id))
    return company_id


@pytest.fixture
def client(db, company):
    """IGSID Клиента. Его данные стираются через delete_client после теста."""
    igsid = f"igsid-{uuid.uuid4().hex[:8]}"
    yield igsid
    db.execute("select delete_client(%s, 'instagram', %s)", (company, igsid))


def saved_messages(db, mid):
    return db.execute(
        "select m.direction, m.text, v.channel, v.sender_id"
        " from messages m join conversations v on v.id = m.conversation_id"
        " where m.provider_message_id = %s",
        (mid,),
    ).fetchall()


def sent(fake):
    return fake.requests(SEND_PATH)


def message_count(db):
    return db.execute("select count(*) from messages").fetchone()[0]


def test_client_message_is_saved_and_answered_through_instagram(db, fake, meta, client):
    respond_with(fake, assistant_reply(reply="Dzień dobry! W czym pomóc?"))
    mid = new_mid()

    response = meta.post(instagram_payload(ACCOUNT_ID, client, "Ile kosztuje wymiana oleju?", mid))

    assert response.status_code == 200
    request = eventually(lambda: sent(fake))[0]
    assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert request.json() == {
        "recipient": {"id": client},
        "messaging_type": "RESPONSE",
        "message": {"text": "Dzień dobry! W czym pomóc?"},
    }
    assert saved_messages(db, mid) == [("in", "Ile kosztuje wymiana oleju?", "instagram", client)]


def test_wrong_signature_is_rejected_and_nothing_saved(db, fake, meta, client):
    payload = instagram_payload(ACCOUNT_ID, client, "Fałszywka")

    response = meta.post(payload, signature=sign(b"other body"))

    assert response.status_code == 401
    stays(lambda: message_count(db) == 0)
    assert sent(fake) == []


def test_echo_of_business_message_is_acknowledged_and_ignored(db, fake, meta, client):
    response = meta.post(instagram_echo_payload(ACCOUNT_ID, client, "Odpowiedź z aplikacji Instagram"))

    assert response.status_code == 200
    stays(lambda: message_count(db) == 0)
    assert fake.requests("/openrouter") == []


def test_repeated_webhook_gets_one_reply(fake, meta, client):
    respond_with(fake, assistant_reply())
    payload = instagram_payload(ACCOUNT_ID, client, "Dzień dobry", new_mid())

    meta.post(payload)
    meta.post(payload)

    eventually(lambda: sent(fake))
    stays(lambda: len(sent(fake)) == 1)


def test_conversation_lands_in_crm_as_instagram(fake, crm, meta, client):
    respond_with(fake, assistant_reply(reply="Dzień dobry!"))

    meta.post(instagram_payload(ACCOUNT_ID, client, "Dzień dobry", new_mid()))

    assert eventually(lambda: len(crm_conversation_messages(crm, client)) == 2 and crm_conversation_messages(crm, client)) == [
        ("in", "client", "Dzień dobry"),
        ("out", "assistant", "Dzień dobry!"),
    ]


def test_employee_reply_after_24_hours_is_sent_with_human_agent_tag(db, n8n_url, fake, meta, client):
    respond_with(fake, assistant_reply(reply="Sprawdzę i dam znać."))
    meta.post(instagram_payload(ACCOUNT_ID, client, "Kiedy auto będzie gotowe?", new_mid()))
    eventually(lambda: sent(fake))
    db.execute(
        "update messages m set created_at = now() - interval '25 hours'"
        " from conversations c where c.id = m.conversation_id and c.sender_id = %s",
        (client,),
    )

    employee_reply(n8n_url, client, "Przepraszamy za zwłokę, auto jest gotowe.", channel="instagram")

    tagged = {
        "recipient": {"id": client},
        "messaging_type": "MESSAGE_TAG",
        "tag": "HUMAN_AGENT",
        "message": {"text": "Przepraszamy za zwłokę, auto jest gotowe."},
    }
    assert eventually(lambda: tagged in [r.json() for r in sent(fake)])


def crm_conversation_messages(crm, igsid):
    """Сообщения Беседы Клиента Instagram в CRM, отсортированы: внутри секунды порядок не определён."""
    found = [c for c in crm.records("Conversation") if (c["channel"], c["senderId"]) == ("instagram", igsid)]
    if len(found) != 1:
        return []
    messages = crm.related("Conversation", found[0]["id"], "messages")
    return sorted((m["direction"], m["author"], m["text"]) for m in messages)

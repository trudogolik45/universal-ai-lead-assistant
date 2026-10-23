"""Беседа в CRM: сообщение Клиента и ответ Ассистента n8n пишет в Беседу Клиента в EspoCRM
через переходник CRM. Недоступная CRM не теряет сообщения: retry дописывает их после восстановления.

Главный шов: подписанный вебхук Meta на входе, записи фейковой EspoCRM (tests/fake_espocrm.py) на выходе.
"""

import uuid

import pytest

from tests.factories import create_company
from tests.meta import MetaClient, messenger_payload, new_mid
from tests.openrouter import assistant_reply, respond_with
from tests.polling import eventually, stays
from tests.retry import run_retry

PAGE_ID = "page-400"
SEND_API_PATH = "/meta/me/messages"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Crm Co")
    db.execute("update companies set messenger_page_id = %s where id = %s", (PAGE_ID, company_id))
    return company_id


@pytest.fixture
def client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


def conversations(crm, sender_id):
    return [c for c in crm.records("Conversation") if (c["channel"], c["senderId"]) == ("messenger", sender_id)]


def conversation_messages(crm, sender_id):
    """Сообщения Беседы Клиента в CRM по порядку: (направление, автор, текст)."""
    found = conversations(crm, sender_id)
    if len(found) != 1:
        return []
    messages = crm.related("Conversation", found[0]["id"], "messages", order_by="sentAt")
    return [(m["direction"], m["author"], m["text"]) for m in messages]


def replies_sent(fake):
    return fake.requests(SEND_API_PATH)


def crm_write_stale(db, minutes=10):
    """Запись в CRM начата minutes назад: retry дописывает только то, что уже не в работе."""
    db.execute("update messages set crm_claimed_at = now() - make_interval(mins => %s)", (minutes,))


def test_client_message_and_assistant_reply_appear_in_one_conversation(fake, crm, meta, client):
    respond_with(fake, assistant_reply(reply="Dzień dobry, w czym pomóc?"))
    mid = new_mid()

    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje wymiana oleju?", mid))

    assert eventually(lambda: len(conversation_messages(crm, client)) == 2 and conversation_messages(crm, client)) == [
        ("in", "client", "Ile kosztuje wymiana oleju?"),
        ("out", "assistant", "Dzień dobry, w czym pomóc?"),
    ]
    incoming = crm.related("Conversation", conversations(crm, client)[0]["id"], "messages", order_by="sentAt")[0]
    assert incoming["providerMessageId"] == mid


def test_next_message_of_client_goes_to_the_same_conversation(fake, crm, meta, client):
    respond_with(fake, assistant_reply(reply="Dzień dobry!"), assistant_reply(reply="Zapraszamy jutro."))
    meta.post(messenger_payload(PAGE_ID, client, "Dzień dobry"))
    eventually(lambda: len(conversation_messages(crm, client)) == 2)

    meta.post(messenger_payload(PAGE_ID, client, "Czy jutro jest wolne?"))

    eventually(lambda: len(conversation_messages(crm, client)) == 4)
    assert len(conversations(crm, client)) == 1
    assert conversation_messages(crm, client)[2:] == [
        ("in", "client", "Czy jutro jest wolne?"),
        ("out", "assistant", "Zapraszamy jutro."),
    ]


def test_unavailable_crm_does_not_lose_messages_and_retry_writes_them_after_recovery(
    db, fake, crm, meta, n8n_url, client
):
    respond_with(fake, assistant_reply(reply="Dzień dobry, w czym pomóc?"))
    with crm.unavailable():
        meta.post(messenger_payload(PAGE_ID, client, "Dzień dobry"))
        eventually(lambda: replies_sent(fake))
        stays(lambda: conversations(crm, client) == [])

    crm_write_stale(db)
    run_retry(n8n_url)

    assert eventually(lambda: len(conversation_messages(crm, client)) == 2 and conversation_messages(crm, client)) == [
        ("in", "client", "Dzień dobry"),
        ("out", "assistant", "Dzień dobry, w czym pomóc?"),
    ]
    assert len(replies_sent(fake)) == 1


def test_retry_does_not_write_messages_already_in_crm_again(db, fake, crm, meta, n8n_url, client):
    respond_with(fake, assistant_reply())
    meta.post(messenger_payload(PAGE_ID, client, "Dzień dobry"))
    eventually(lambda: len(conversation_messages(crm, client)) == 2)

    crm_write_stale(db)
    run_retry(n8n_url)

    stays(lambda: len(crm.records("Message")) == 2, seconds=5)

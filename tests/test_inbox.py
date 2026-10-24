"""Буфер входящих: подписанный вебхук Meta ложится в Postgres до обработки, Meta сразу получает 200.
Обработка идёт из буфера: дубль вебхука не даёт второго ответа, упавшая обработка повторяется retry."""

import uuid
from contextlib import contextmanager

import pytest

from tests import knowledge
from tests.factories import create_company
from tests.fake_server import Response
from tests.meta import MetaClient, messenger_payload, new_mid
from tests.openrouter import assistant_reply, respond_with
from tests.polling import eventually, stays
from tests.retry import run_retry, sending_stale
from tests.telegram import ALERT_CHAT_ID, sent_to_telegram

PAGE_ID = "page-300"
SEND_API_PATH = "/meta/me/messages"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Inbox Co")
    db.execute("update companies set messenger_page_id = %s where id = %s", (PAGE_ID, company_id))
    return company_id


@pytest.fixture
def client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


@contextmanager
def table_unavailable(db, table):
    """Сбой Postgres на одной таблице: запросы к ней падают, пока блок не закончится."""
    db.execute(f"alter table {table} rename to {table}_unavailable")
    try:
        yield
    finally:
        db.execute(f"alter table {table}_unavailable rename to {table}")


def replies_sent(fake):
    return fake.requests(SEND_API_PATH)


def test_webhook_is_not_acknowledged_until_buffered(db, fake, meta, client):
    with table_unavailable(db, "inbox"):
        response = meta.post(messenger_payload(PAGE_ID, client, "Dzień dobry"))

    assert response.status_code != 200
    stays(lambda: replies_sent(fake) == [])


def test_repeated_webhook_gets_one_reply(fake, meta, client):
    respond_with(fake, assistant_reply())
    payload = messenger_payload(PAGE_ID, client, "Dzień dobry", new_mid())

    first, second = meta.post(payload), meta.post(payload)

    assert (first.status_code, second.status_code) == (200, 200)
    eventually(lambda: replies_sent(fake))
    stays(lambda: len(replies_sent(fake)) == 1)


def processing_stale(db, minutes=10):
    """Обработку взяли minutes назад: retry повторяет только то, что уже не в работе."""
    db.execute("update inbox set claimed_at = now() - make_interval(mins => %s)", (minutes,))


def test_failed_processing_is_retried_from_buffer(db, fake, meta, n8n_url, client):
    respond_with(fake, assistant_reply(reply="Dzień dobry, w czym pomóc?"))
    knowledge.respond_with(fake, Response(500, {}))
    response = meta.post(messenger_payload(PAGE_ID, client, "Dzień dobry"))
    stays(lambda: replies_sent(fake) == [])
    assert response.status_code == 200

    knowledge.respond_with(fake, [])
    processing_stale(db)
    run_retry(n8n_url)

    reply = eventually(lambda: replies_sent(fake))[0].json()
    assert reply["recipient"] == {"id": client}
    assert reply["message"] == {"text": "Dzień dobry, w czym pomóc?"}


def test_processed_message_is_not_answered_again_by_retry(db, fake, meta, n8n_url, client):
    respond_with(fake, assistant_reply())
    meta.post(messenger_payload(PAGE_ID, client, "Dzień dobry"))
    eventually(lambda: replies_sent(fake))

    processing_stale(db)
    run_retry(n8n_url)

    stays(lambda: len(replies_sent(fake)) == 1)


def attempt_done(fake, attempt):
    """Попытка обработки дошла до Базы знаний: узел читает её дважды, прежде чем сдаться."""
    eventually(lambda: len(knowledge.knowledge_requests(fake)) >= 2 * attempt)


def test_processing_failing_three_times_alerts_developers_once(db, fake, meta, n8n_url, client):
    knowledge.respond_with(fake, Response(500, {}))
    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje wymiana oleju?"))
    attempt_done(fake, 1)
    processing_stale(db)
    run_retry(n8n_url)
    attempt_done(fake, 2)
    stays(lambda: sent_to_telegram(fake) == [])

    for attempt in (3, 4):
        processing_stale(db)
        run_retry(n8n_url)
        attempt_done(fake, attempt)

    [alert] = eventually(lambda: sent_to_telegram(fake))
    assert alert["chat_id"] == ALERT_CHAT_ID
    for expected in ("Inbox Co", client, "Ile kosztuje wymiana oleju?"):
        assert expected in alert["text"]
    stays(lambda: len(sent_to_telegram(fake)) == 1)


def test_reply_lost_to_channel_failure_is_sent_again_by_retry(db, fake, meta, n8n_url, client):
    respond_with(fake, assistant_reply(reply="Dzień dobry, w czym pomóc?"))
    fake.respond("POST", SEND_API_PATH, Response(500, {}), Response(200, {}))
    meta.post(messenger_payload(PAGE_ID, client, "Dzień dobry"))
    eventually(lambda: replies_sent(fake))

    sending_stale(db)
    run_retry(n8n_url)

    assert eventually(lambda: len(replies_sent(fake)) == 2 and replies_sent(fake))[1].json()["message"] == {
        "text": "Dzień dobry, w czym pomóc?"
    }
    sending_stale(db)
    run_retry(n8n_url)
    stays(lambda: len(replies_sent(fake)) == 2)

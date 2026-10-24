"""Алерт «AI не отвечает» уходит в группу Telegram разработчиков, а не Заказчику.

Главный шов: подписанный вебхук Meta на входе, sendMessage Bot API фейка на выходе.
"""

import uuid

import pytest

from tests.factories import create_company
from tests.fake_server import Response
from tests.meta import MetaClient, messenger_payload
from tests.openrouter import respond_with
from tests.polling import eventually, stays
from tests.retry import run_retry
from tests.telegram import ALERT_CHAT_ID, SEND_MESSAGE_PATH, sent_to_telegram, telegram_fails

PAGE_ID = "page-700"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Alert Co")
    db.execute("update companies set messenger_page_id = %s where id = %s", (PAGE_ID, company_id))
    return company_id


@pytest.fixture
def client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


def ai_alert_sent(db):
    return db.execute("select count(*) from messages where ai_alert_sent_at is not null").fetchone()[0]


def test_two_failed_ai_calls_alert_developers_with_last_message(db, fake, meta, client):
    respond_with(fake, Response(500, {}))

    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje montaż?"))

    alert = eventually(lambda: sent_to_telegram(fake))[0]
    assert alert["chat_id"] == ALERT_CHAT_ID
    for expected in ("Alert Co", client, "Ile kosztuje montaż?"):
        assert expected in alert["text"]
    eventually(lambda: ai_alert_sent(db))
    stays(lambda: len(sent_to_telegram(fake)) == 1)


def test_ai_alert_lost_to_telegram_failure_is_sent_once_by_retry(db, fake, meta, client, n8n_url):
    respond_with(fake, Response(500, {}))
    telegram_fails(fake)
    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje montaż?"))
    eventually(lambda: sent_to_telegram(fake))
    stays(lambda: not ai_alert_sent(db))
    db.execute("update messages set ai_failed_at = ai_failed_at - interval '5 minutes'")
    fake.respond("POST", SEND_MESSAGE_PATH, Response(200, {"ok": True}))

    run_retry(n8n_url)
    eventually(lambda: ai_alert_sent(db))
    run_retry(n8n_url)

    stays(lambda: len(sent_to_telegram(fake)) == 2)
    assert "Ile kosztuje montaż?" in sent_to_telegram(fake)[1]["text"]

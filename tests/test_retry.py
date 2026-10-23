"""Workflow по расписанию: повторы (алерты «AI не отвечает», буфер, запись в CRM) и закрытие Бесед
после 7 дней тишины.

Тест не ждёт расписания: тот же workflow запускает вебхук /webhook/retry с секретом из env.
"""

import pytest

from tests.factories import create_company, open_conversation
from tests.polling import eventually, stays
from tests.retry import run_retry
from tests.telegram import ALERT_CHAT_ID, sent_to_telegram


@pytest.fixture
def company(db):
    return create_company(db, "Retry Co")


def failed_ai_message(db, company_id, minutes_ago):
    """Входящее Сообщение, на которое AI не ответил, алерт о нём ещё не ушёл."""
    conversation_id = open_conversation(db, company_id, sender_id=f"psid-ai-{minutes_ago}")
    return db.execute(
        "insert into messages (company_id, conversation_id, direction, text, ai_failed_at)"
        " values (%s, %s, 'in', 'Ile kosztuje montaż?', now() - make_interval(mins => %s)) returning id",
        (company_id, conversation_id, minutes_ago),
    ).fetchone()[0]


def ai_alert_sent_at(db, message_id):
    return db.execute("select ai_alert_sent_at from messages where id = %s", (message_id,)).fetchone()[0]


def test_missed_ai_alert_is_sent_once_by_retry(db, fake, n8n_url, company):
    message_id = failed_ai_message(db, company, minutes_ago=5)

    run_retry(n8n_url)
    alert = eventually(lambda: sent_to_telegram(fake))[0]
    eventually(lambda: ai_alert_sent_at(db, message_id))
    run_retry(n8n_url)

    assert alert["chat_id"] == ALERT_CHAT_ID
    assert "Ile kosztuje montaż?" in alert["text"]
    stays(lambda: len(sent_to_telegram(fake)) == 1)


def test_fresh_ai_alert_is_left_to_main_flow(db, fake, n8n_url, company):
    failed_ai_message(db, company, minutes_ago=0)

    run_retry(n8n_url)

    stays(lambda: not sent_to_telegram(fake), seconds=3)


def silent_for(db, conversation_id, days):
    db.execute(
        "update conversations set last_message_at = now() - make_interval(days => %s) where id = %s",
        (days, conversation_id),
    )


def conversation_status(db, conversation_id):
    return db.execute("select status from conversations where id = %s", (conversation_id,)).fetchone()[0]


def lead_status(db, conversation_id):
    return db.execute("select status from leads where conversation_id = %s", (conversation_id,)).fetchone()[0]


@pytest.mark.parametrize("status", ["open", "handoff"])
def test_conversation_silent_for_seven_days_is_closed_with_its_lead(db, fake, n8n_url, status):
    company_id = create_company(db, "Silent Co")
    conversation_id = open_conversation(db, company_id, status=status)
    db.execute(
        "insert into leads (company_id, conversation_id, status) values (%s, %s, 'collecting')",
        (company_id, conversation_id),
    )
    silent_for(db, conversation_id, days=8)

    run_retry(n8n_url)

    eventually(lambda: conversation_status(db, conversation_id) == "closed")
    eventually(lambda: lead_status(db, conversation_id) == "closed")


def test_conversation_with_recent_messages_stays_open(db, fake, n8n_url):
    company_id = create_company(db, "Silent Co")
    recent = open_conversation(db, company_id, sender_id="psid-recent")
    silent = open_conversation(db, company_id, sender_id="psid-silent")
    silent_for(db, recent, days=6)
    silent_for(db, silent, days=8)

    run_retry(n8n_url)

    eventually(lambda: conversation_status(db, silent) == "closed")
    assert conversation_status(db, recent) == "open"


def test_wrong_secret_is_rejected_and_runs_nothing(db, fake, n8n_url, company):
    conversation_id = open_conversation(db, company)
    silent_for(db, conversation_id, days=8)

    response = run_retry(n8n_url, secret="wrong")

    assert response.status_code == 401
    stays(lambda: conversation_status(db, conversation_id) == "open")

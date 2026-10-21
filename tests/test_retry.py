"""Workflow по расписанию: повторная доставка Заявок и закрытие Бесед после 7 дней тишины.

Тест не ждёт расписания: тот же workflow запускает вебхук /webhook/retry с секретом из env.
"""

import httpx
import pytest

from tests.factories import create_company, open_conversation
from tests.fake_server import Response
from tests.polling import eventually, stays
from tests.telegram import SEND_MESSAGE_PATH, sent_to_telegram, telegram_fails

# Значение из docker-compose.test.yml.
RETRY_SECRET = "test-retry-secret"
SPREADSHEET_ID = "spreadsheet-900"
CHAT_ID = "-1009000000000"
SPREADSHEET_PATH = f"/sheets/v4/spreadsheets/{SPREADSHEET_ID}"
APPEND_PATH = f"{SPREADSHEET_PATH}/values/'Leads'!A1:append"


def run_retry(n8n_url, secret=RETRY_SECRET) -> httpx.Response:
    return httpx.post(f"{n8n_url}/webhook/retry", headers={"X-Retry-Secret": secret}, timeout=10)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Retry Co")
    db.execute(
        "update companies set sheets_spreadsheet_id = %s where id = %s",
        (SPREADSHEET_ID, company_id),
    )
    return company_id


@pytest.fixture
def google(fake):
    """Google отдаёт токен, в таблице уже есть лист Leads."""
    fake.respond("POST", "/google-oauth/token", Response(200, {"access_token": "t", "expires_in": 3600}))
    fake.respond("GET", SPREADSHEET_PATH, Response(200, {"sheets": [{"properties": {"title": "Leads"}}]}))
    return fake


def undelivered_lead(db, company_id, status="qualified", sender_id="psid-1", telegram_sent=False):
    conversation_id = open_conversation(db, company_id, sender_id=sender_id)
    return db.execute(
        "insert into leads (company_id, conversation_id, status, name, telegram_sent_at)"
        " values (%s, %s, %s, 'Anna', case when %s then now() end) returning id",
        (company_id, conversation_id, status, telegram_sent),
    ).fetchone()[0]


def lead_column(db, lead_id, column):
    return db.execute(f"select {column} from leads where id = %s", (lead_id,)).fetchone()[0]


def append_attempts(fake):
    return [r for r in fake.requests(SPREADSHEET_PATH + "/values/") if r.method == "POST"]


def test_lead_left_off_sheet_is_delivered_once_sheets_recovers(db, google, n8n_url, company):
    lead_id = undelivered_lead(db, company)
    google.respond("POST", APPEND_PATH, Response(500, {"error": "backend"}))

    assert run_retry(n8n_url).status_code == 200
    eventually(lambda: append_attempts(google))
    stays(lambda: lead_column(db, lead_id, "sheets_delivered_at") is None)

    google.respond("POST", APPEND_PATH, Response(200, {}))
    run_retry(n8n_url)
    eventually(lambda: lead_column(db, lead_id, "sheets_delivered_at"))

    run_retry(n8n_url)
    stays(lambda: len(append_attempts(google)) == 2)



def test_lead_failing_delivery_does_not_hold_back_other_leads(db, google, n8n_url, company):
    broken_company = create_company(db, "Broken Sheet Co")
    db.execute(
        "update companies set sheets_spreadsheet_id = 'broken-sheet' where id = %s", (broken_company,)
    )
    broken_lead = undelivered_lead(db, broken_company)
    lead_id = undelivered_lead(db, company, sender_id="psid-2")
    google.respond("GET", "/sheets/v4/spreadsheets/broken-sheet", Response(500, {"error": "backend"}))

    run_retry(n8n_url)

    eventually(lambda: lead_column(db, lead_id, "sheets_delivered_at"))
    assert lead_column(db, broken_lead, "sheets_delivered_at") is None

@pytest.fixture
def telegram_company(db):
    company_id = create_company(db, "Retry Telegram Co")
    db.execute("update companies set telegram_chat_id = %s where id = %s", (CHAT_ID, company_id))
    return company_id


def test_lead_missed_in_telegram_is_announced_once_telegram_recovers(db, fake, n8n_url, telegram_company):
    lead_id = undelivered_lead(db, telegram_company, status="needs_human")
    telegram_fails(fake)

    run_retry(n8n_url)
    eventually(lambda: sent_to_telegram(fake))
    stays(lambda: lead_column(db, lead_id, "telegram_sent_at") is None)

    fake.respond("POST", SEND_MESSAGE_PATH, Response(200, {"ok": True}))
    run_retry(n8n_url)
    eventually(lambda: lead_column(db, lead_id, "telegram_sent_at"))

    run_retry(n8n_url)
    stays(lambda: len(sent_to_telegram(fake)) == 2)


def test_lead_already_announced_is_not_sent_to_telegram_again(db, google, n8n_url, company):
    db.execute("update companies set telegram_chat_id = %s where id = %s", (CHAT_ID, company))
    lead_id = undelivered_lead(db, company, telegram_sent=True)

    run_retry(n8n_url)

    eventually(lambda: lead_column(db, lead_id, "sheets_delivered_at"))
    stays(lambda: not sent_to_telegram(google))


def test_lead_still_being_collected_is_not_delivered(db, google, n8n_url, company):
    undelivered_lead(db, company, status="collecting")

    run_retry(n8n_url)

    stays(lambda: not append_attempts(google), seconds=3)


def test_wrong_secret_is_rejected_and_runs_nothing(db, google, n8n_url, company):
    lead_id = undelivered_lead(db, company)

    response = run_retry(n8n_url, secret="wrong")

    assert response.status_code == 401
    stays(lambda: not append_attempts(google))
    assert lead_column(db, lead_id, "sheets_delivered_at") is None


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

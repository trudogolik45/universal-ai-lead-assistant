"""Доставка Заявки: строка на лист Leads Google-таблицы и CRM-webhook при первом qualified."""

import uuid
from datetime import datetime
from urllib.parse import parse_qs, unquote
from zoneinfo import ZoneInfo

import pytest

from tests.factories import create_company
from tests.fake_server import Response
from tests.google import JWT_GRANT, SCOPE
from tests.meta import MetaClient, messenger_payload
from tests.openrouter import assistant_reply, respond_with
from tests.polling import eventually, stays

PAGE_ID = "page-600"
SPREADSHEET_ID = "spreadsheet-600"
ACCESS_TOKEN = "test-google-access-token"
TOKEN_PATH = "/google-oauth/token"
SPREADSHEET_PATH = f"/sheets/v4/spreadsheets/{SPREADSHEET_ID}"
APPEND_PATH = f"{SPREADSHEET_PATH}/values/'Leads'!A1:append"
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
    company_id = create_company(db, "Delivery Co")
    db.execute(
        "update companies set messenger_page_id = %s, sheets_spreadsheet_id = %s where id = %s",
        (PAGE_ID, SPREADSHEET_ID, company_id),
    )
    return company_id


@pytest.fixture
def client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


@pytest.fixture
def google(fake):
    """Google отдаёт токен, в таблице уже есть лист Leads."""
    fake.respond("POST", TOKEN_PATH, Response(200, {"access_token": ACCESS_TOKEN, "expires_in": 3600}))
    spreadsheet_has_sheets(fake, "Leads")
    return fake


def spreadsheet_has_sheets(fake, *titles):
    sheets = [{"properties": {"title": title}} for title in titles]
    fake.respond("GET", SPREADSHEET_PATH, Response(200, {"sheets": sheets}))


def qualify(fake, meta, client, lead_data=FULL_LEAD):
    respond_with(fake, assistant_reply(intent="booking", lead_data=lead_data, qualified=True))
    meta.post(messenger_payload(PAGE_ID, client, "Anna Kowalska, +48 600 100 200, montaż szafy"))


def appended_rows(fake):
    return [
        row
        for request in fake.requests(SPREADSHEET_PATH + "/values/")
        if request.method == "POST" and request.path.split("?")[0].endswith(":append")
        for row in request.json()["values"]
    ]


def headers(request):
    return {name.lower(): value for name, value in request.headers.items()}


def delivered_at(db):
    row = db.execute("select sheets_delivered_at from leads").fetchone()
    return row and row[0]


def conversation_id(db):
    return str(db.execute("select id from conversations").fetchone()[0])


def today_in_warsaw():
    return datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%Y-%m-%d")


def test_qualified_lead_is_appended_to_leads_sheet_and_marked_delivered(db, google, meta, client):
    qualify(google, meta, client)

    rows = eventually(lambda: appended_rows(google))
    eventually(lambda: delivered_at(db))
    date, *rest = rows[0]
    assert date.startswith(today_in_warsaw())
    assert rest == [
        "messenger",
        "Anna Kowalska",
        "+48 600 100 200",
        "Montaż mebli",
        "Szafa z IKEA",
        "piątek rano",
        "booking",
        "qualified",
        conversation_id(db),
    ]
    assert len(rows) == 1


def test_google_token_is_requested_with_service_account_jwt_and_used_for_sheets(
    db, google, meta, client, service_account
):
    qualify(google, meta, client)

    eventually(lambda: delivered_at(db))
    form = parse_qs(google.requests(TOKEN_PATH)[0].body.decode())
    assert form["grant_type"] == [JWT_GRANT]
    claims = service_account.verify(form["assertion"][0])
    assert claims["iss"] == service_account.email
    assert claims["scope"] == SCOPE
    assert claims["aud"] == google.container_url(TOKEN_PATH)
    sheets_requests = google.requests("/sheets")
    assert sheets_requests
    assert all(headers(r)["authorization"] == f"Bearer {ACCESS_TOKEN}" for r in sheets_requests)


def test_missing_leads_sheet_is_created_with_header_and_other_sheets_untouched(db, google, meta, client):
    spreadsheet_has_sheets(google, "Arkusz1", "Faktury")

    qualify(google, meta, client)

    eventually(lambda: delivered_at(db))
    batch_updates = [r.json() for r in google.requests(SPREADSHEET_PATH + ":batchUpdate")]
    assert batch_updates == [{"requests": [{"addSheet": {"properties": {"title": "Leads"}}}]}]
    header, row = appended_rows(google)
    assert header == [
        "Дата", "Канал", "Имя", "Контакт", "Услуга", "Описание",
        "Желаемая дата", "Намерение", "Статус", "ID беседы",
    ]
    assert row[2] == "Anna Kowalska"
    assert {unquote(r.path.split("?")[0]) for r in google.requests(SPREADSHEET_PATH + "/values/")} == {
        APPEND_PATH
    }


def test_lead_qualified_again_does_not_append_second_row(db, google, meta, client):
    qualify(google, meta, client)
    first_delivery = eventually(lambda: delivered_at(db))

    qualify(google, meta, client)

    stays(lambda: len(appended_rows(google)) == 1, seconds=3)
    assert delivered_at(db) == first_delivery


def test_failed_sheets_write_leaves_lead_undelivered(db, google, meta, client):
    google.respond("POST", APPEND_PATH, Response(500, {"error": "backend"}))

    qualify(google, meta, client)

    eventually(lambda: appended_rows(google))
    stays(lambda: delivered_at(db) is None, seconds=3)
    assert db.execute("select status from leads").fetchone()[0] == "qualified"


def test_lead_json_is_posted_to_crm_webhook_when_set(db, google, meta, client, company):
    db.execute(
        "update companies set crm_webhook_url = %s where id = %s",
        (google.container_url("/crm/hook"), company),
    )

    qualify(google, meta, client)

    crm = eventually(lambda: google.requests("/crm/hook"))
    lead_id, conversation = db.execute("select id, conversation_id from leads").fetchone()
    body = crm[0].json()
    assert body.pop("created_at")
    assert body == {
        "lead_id": str(lead_id),
        "company_id": str(company),
        "conversation_id": str(conversation),
        "channel": "messenger",
        "status": "qualified",
        **FULL_LEAD,
        "intent": "booking",
    }
    assert [r.method for r in crm] == ["POST"]


def test_crm_webhook_is_not_called_when_not_set(db, google, meta, client):
    qualify(google, meta, client)

    eventually(lambda: delivered_at(db))
    stays(lambda: not google.requests("/crm"), seconds=2)

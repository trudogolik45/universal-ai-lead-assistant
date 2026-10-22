"""Доставка Заявки в настоящую тестовую Google-таблицу: тест читает строку обратно.

Нужны env: GOOGLE_SERVICE_ACCOUNT_EMAIL, GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY и
GOOGLE_SHEETS_TEST_SPREADSHEET_ID (таблица расшарена на service account как Editor).
Без них тест пропускается. Поднимает отдельный стенд: n8n ходит в настоящий Google,
остальные внешние API — на фейк. Лист создаётся свой на прогон и удаляется после.
"""

import os
import uuid

import httpx
import psycopg
import pytest

from scripts.migrate import migrate
from tests.factories import create_company
from tests.google import ServiceAccount, read_values
from tests.meta import MetaClient, messenger_payload
from tests.openrouter import assistant_reply, respond_with
from tests.polling import eventually
from tests.stand import Stand

REQUIRED_ENV = (
    "GOOGLE_SERVICE_ACCOUNT_EMAIL",
    "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY",
    "GOOGLE_SHEETS_TEST_SPREADSHEET_ID",
)
SHEETS_BASE_URL = "https://sheets.googleapis.com"
OAUTH_BASE_URL = "https://oauth2.googleapis.com"
PAGE_ID = "page-google"

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(name) for name in REQUIRED_ENV),
    reason="Нет доступа к тестовой Google-таблице: " + ", ".join(REQUIRED_ENV),
)


@pytest.fixture(scope="module")
def account():
    key = os.environ["GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY"].replace("\\n", "\n")
    return ServiceAccount(os.environ["GOOGLE_SERVICE_ACCOUNT_EMAIL"], key)


@pytest.fixture(scope="module")
def google_stand(stand, fake_server, account):
    """Отдельный compose-проект: стенд с фейковым Google не перезапускается."""
    real = Stand(project=stand.project + "-google")
    database_url = real.up_postgres()
    migrate(database_url)
    n8n_url = real.up_n8n({
        **fake_server.base_urls(),
        **account.env(),
        "GOOGLE_SHEETS_BASE_URL": SHEETS_BASE_URL,
        "GOOGLE_OAUTH_BASE_URL": OAUTH_BASE_URL,
    })
    yield database_url, n8n_url
    if not os.environ.get("STAND_KEEP"):
        real.down()


@pytest.fixture
def sheet_name(account):
    """Свой лист на прогон; после теста удаляется, чужие листы не трогаются."""
    name = f"Leads-test-{uuid.uuid4().hex[:8]}"
    yield name
    spreadsheet_id = os.environ["GOOGLE_SHEETS_TEST_SPREADSHEET_ID"]
    headers = {"Authorization": f"Bearer {account.access_token(OAUTH_BASE_URL + '/token')}"}
    url = f"{SHEETS_BASE_URL}/v4/spreadsheets/{spreadsheet_id}"
    sheets = httpx.get(url, headers=headers, params={"fields": "sheets.properties"}).json()["sheets"]
    for sheet in sheets:
        if sheet["properties"]["title"] == name:
            request = {"deleteSheet": {"sheetId": sheet["properties"]["sheetId"]}}
            httpx.post(f"{url}:batchUpdate", headers=headers, json={"requests": [request]})


def test_qualified_lead_row_is_read_back_from_real_spreadsheet(google_stand, fake, account, sheet_name):
    database_url, n8n_url = google_stand
    spreadsheet_id = os.environ["GOOGLE_SHEETS_TEST_SPREADSHEET_ID"]
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute("truncate companies cascade")
        company_id = create_company(db, "Google Co")
        db.execute(
            "update companies set messenger_page_id = %s, sheets_spreadsheet_id = %s,"
            " sheets_sheet_name = %s where id = %s",
            (PAGE_ID, spreadsheet_id, sheet_name, company_id),
        )
        respond_with(fake, assistant_reply(
            intent="estimate",
            lead_data={"name": "Jan Nowak", "contact": "+48 500 000 000", "service": "Remont łazienki"},
            qualified=True,
        ))

        MetaClient(n8n_url).post(messenger_payload(PAGE_ID, "psid-google", "Jan Nowak, remont łazienki"))

        eventually(lambda: db.execute("select sheets_delivered_at from leads").fetchone()[0], timeout=30)
        conversation_id = str(db.execute("select id from conversations").fetchone()[0])

    token = account.access_token(OAUTH_BASE_URL + "/token")
    header, row = read_values(SHEETS_BASE_URL, token, spreadsheet_id, sheet_name)
    assert header[0] == "Дата"
    assert row[1:] == [
        "messenger", "Jan Nowak", "+48 500 000 000", "Remont łazienki", "", "", "estimate",
        "qualified", conversation_id,
    ]

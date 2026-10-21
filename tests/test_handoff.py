import uuid

import pytest

from tests.factories import create_company
from tests.fake_server import Response
from tests.meta import MetaClient, messenger_payload
from tests.openrouter import assistant_reply, completion_requests, respond_with
from tests.polling import eventually, stays
from tests.telegram import TelegramClient, answered_callbacks, callback_data, sent_to_telegram

PAGE_ID = "page-800"
SEND_API_PATH = "/meta/me/messages"
CHAT_ID = "-1008000000000"
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
def telegram(n8n_url):
    return TelegramClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Handoff Co")
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


def handoff_reply(reason="Brak ceny w bazie wiedzy", language="pl"):
    return assistant_reply(
        reply="Cena to 50 zł.", language=language, needs_human=True, handoff_reason=reason,
    )


def lead(db):
    return db.execute("select status, handoff_reason from leads").fetchone()


def conversation_statuses(db):
    return [row[0] for row in db.execute("select status from conversations order by created_at").fetchall()]


def sent_texts(fake):
    return [request.json()["message"]["text"] for request in fake.requests(SEND_API_PATH)]


def test_unknown_question_hands_conversation_off_to_human(db, fake, meta, client):
    respond_with(fake, handoff_reply())

    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje przewóz pianina?"))

    assert eventually(lambda: lead(db) == ("needs_human", "Brak ceny w bazie wiedzy"))
    assert conversation_statuses(db) == ["handoff"]


@pytest.mark.parametrize(
    ("language", "expected"),
    [("pl", "przekaz"), ("en", "pass"), ("ru", "переда")],
)
def test_client_asking_for_human_gets_handoff_notice_in_own_language(db, fake, meta, client, language, expected):
    respond_with(fake, handoff_reply(reason="Klient prosi o człowieka", language=language))

    meta.post(messenger_payload(PAGE_ID, client, "Chcę rozmawiać z człowiekiem"))

    text = eventually(lambda: sent_texts(fake))[0]
    assert expected in text.lower()
    assert "50 zł" not in text


def lead_id(db):
    return db.execute("select id from leads").fetchone()[0]


def telegram_sent(db):
    return db.execute("select count(*) from leads where telegram_sent_at is not null").fetchone()[0]


def handoff_sent(db):
    return db.execute("select count(*) from leads where handoff_sent_at is not null").fetchone()[0]


def test_handoff_summary_with_resume_and_close_buttons_goes_to_customer_group(db, fake, meta, client):
    respond_with(fake, handoff_reply())

    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje przewóz pianina?"))

    summary = eventually(lambda: sent_to_telegram(fake))[0]
    lead = lead_id(db)
    assert summary["chat_id"] == CHAT_ID
    for expected in ("Handoff Co", client, "Brak ceny w bazie wiedzy", "Ile kosztuje przewóz pianina?"):
        assert expected in summary["text"]
    assert callback_data(summary) == [f"resume:{lead}", f"close:{lead}"]
    eventually(lambda: handoff_sent(db))


def test_handoff_after_announced_qualified_lead_still_sends_summary(db, fake, meta, client):
    respond_with(
        fake,
        assistant_reply(intent="booking", lead_data=FULL_LEAD, qualified=True),
        handoff_reply(reason="Klient prosi o człowieka"),
    )

    meta.post(messenger_payload(PAGE_ID, client, "Anna, +48 600 100 200, szafa z IKEA w piątek rano"))
    eventually(lambda: telegram_sent(db))
    meta.post(messenger_payload(PAGE_ID, client, "Chcę rozmawiać z człowiekiem"))

    messages = eventually(lambda: len(sent_to_telegram(fake)) == 2 and sent_to_telegram(fake))
    assert "Klient prosi o człowieka" in messages[1]["text"]
    assert len(callback_data(messages[1])) == 2


def hand_off(db, fake, meta, client, *replies):
    """Беседа Клиента передана человеку; replies — следующие ответы AI после передачи."""
    respond_with(fake, handoff_reply(), *replies)
    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje przewóz pianina?"))
    eventually(lambda: handoff_sent(db))
    return lead_id(db)


def lead_status(db):
    return db.execute("select status from leads").fetchone()[0]


def lead_statuses(db):
    return [row[0] for row in db.execute("select status from leads order by created_at").fetchall()]


def test_client_message_in_handoff_is_saved_and_left_to_human(db, fake, meta, client):
    hand_off(db, fake, meta, client)

    meta.post(messenger_payload(PAGE_ID, client, "Halo, jest tam ktoś?"))

    eventually(lambda: db.execute("select count(*) from messages where direction = 'in'").fetchone()[0] == 2)
    stays(lambda: len(completion_requests(fake)) == 1 and len(sent_texts(fake)) == 1)
    assert lead_status(db) == "needs_human"


def test_resume_button_returns_conversation_to_assistant(db, fake, meta, telegram, client):
    lead = hand_off(db, fake, meta, client, assistant_reply(reply="Jak się Pan nazywa?"))

    telegram.press(f"resume:{lead}", CHAT_ID)

    assert eventually(lambda: conversation_statuses(db) == ["open"])
    assert lead_status(db) == "collecting"
    assert eventually(lambda: answered_callbacks(fake))[0]["callback_query_id"].startswith("cb-")
    meta.post(messenger_payload(PAGE_ID, client, "Dobrze, to chcę zamówić przewóz"))
    assert eventually(lambda: "Jak się Pan nazywa?" in sent_texts(fake))


def test_resume_button_with_all_required_fields_makes_lead_qualified(db, fake, meta, telegram, client):
    respond_with(
        fake,
        assistant_reply(intent="booking", lead_data=FULL_LEAD),
        handoff_reply(),
    )
    meta.post(messenger_payload(PAGE_ID, client, "Anna, +48 600 100 200, szafa z IKEA w piątek rano"))
    eventually(lambda: len(sent_texts(fake)) == 1)
    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje przewóz pianina?"))
    eventually(lambda: handoff_sent(db))

    telegram.press(f"resume:{lead_id(db)}", CHAT_ID)

    assert eventually(lambda: lead_status(db) == "qualified")
    assert conversation_statuses(db) == ["open"]


def test_close_button_closes_lead_and_conversation(db, fake, meta, telegram, client):
    lead = hand_off(db, fake, meta, client)

    telegram.press(f"close:{lead}", CHAT_ID)

    assert eventually(lambda: conversation_statuses(db) == ["closed"])
    assert lead_status(db) == "closed"
    assert eventually(lambda: answered_callbacks(fake))


def test_message_after_close_opens_new_conversation_and_lead(db, fake, meta, telegram, client):
    lead = hand_off(db, fake, meta, client, assistant_reply(reply="Dzień dobry!"))
    telegram.press(f"close:{lead}", CHAT_ID)
    eventually(lambda: conversation_statuses(db) == ["closed"])

    meta.post(messenger_payload(PAGE_ID, client, "Dzień dobry, mam nowe pytanie"))

    assert eventually(lambda: conversation_statuses(db) == ["closed", "open"])
    assert eventually(lambda: lead_statuses(db) == ["closed", "collecting"])
    assert eventually(lambda: "Dzień dobry!" in sent_texts(fake))


def test_button_press_with_wrong_secret_is_rejected(db, fake, meta, telegram, client):
    lead = hand_off(db, fake, meta, client)

    response = telegram.press(f"close:{lead}", CHAT_ID, secret="forged")

    assert response.status_code == 401
    stays(lambda: conversation_statuses(db) == ["handoff"] and not answered_callbacks(fake))


def test_button_from_other_group_does_not_touch_lead(db, fake, meta, telegram, client):
    lead = hand_off(db, fake, meta, client)

    telegram.press(f"close:{lead}", "-1009999999999")

    eventually(lambda: answered_callbacks(fake))
    assert conversation_statuses(db) == ["handoff"]
    assert lead_status(db) == "needs_human"


SPREADSHEET_ID = "spreadsheet-800"
SPREADSHEET_PATH = f"/sheets/v4/spreadsheets/{SPREADSHEET_ID}"


@pytest.fixture
def google(db, fake, company):
    """У Заказчика есть таблица, Google отдаёт токен, лист Leads уже есть."""
    db.execute("update companies set sheets_spreadsheet_id = %s where id = %s", (SPREADSHEET_ID, company))
    fake.respond("POST", "/google-oauth/token", Response(200, {"access_token": "t", "expires_in": 3600}))
    fake.respond("GET", SPREADSHEET_PATH, Response(200, {"sheets": [{"properties": {"title": "Leads"}}]}))
    return fake


def sheet_appends(fake):
    return [r for r in fake.requests(SPREADSHEET_PATH + "/values/") if r.method == "POST"]


def new_lead_announcements(fake):
    return [m for m in sent_to_telegram(fake) if m["text"].startswith("Новая заявка")]


def test_resume_to_qualified_announces_new_lead_and_writes_it_to_sheet(db, google, meta, telegram, client):
    respond_with(google, assistant_reply(intent="booking", lead_data=FULL_LEAD), handoff_reply())
    meta.post(messenger_payload(PAGE_ID, client, "Anna, +48 600 100 200, szafa z IKEA w piątek rano"))
    eventually(lambda: len(sent_texts(google)) == 1)
    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje przewóz pianina?"))
    eventually(lambda: handoff_sent(db))

    telegram.press(f"resume:{lead_id(db)}", CHAT_ID)

    announcement = eventually(lambda: new_lead_announcements(google))[0]
    assert callback_data(announcement) == [f"close:{lead_id(db)}"]
    eventually(lambda: sheet_appends(google) and telegram_sent(db))
    stays(lambda: len(new_lead_announcements(google)) == 1 and len(sheet_appends(google)) == 1)


def test_lead_qualified_by_assistant_after_resume_is_announced(db, fake, meta, telegram, client):
    qualified = assistant_reply(intent="booking", lead_data=FULL_LEAD, qualified=True)
    lead = hand_off(db, fake, meta, client, qualified)
    telegram.press(f"resume:{lead}", CHAT_ID)
    eventually(lambda: conversation_statuses(db) == ["open"])
    assert lead_status(db) == "collecting"

    meta.post(messenger_payload(PAGE_ID, client, "Anna, +48 600 100 200, szafa z IKEA w piątek rano"))

    assert eventually(lambda: new_lead_announcements(fake))
    eventually(lambda: telegram_sent(db))

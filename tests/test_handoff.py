import uuid

import pytest

from tests.factories import create_company
from tests.meta import MetaClient, messenger_payload
from tests.openrouter import assistant_reply, completion_requests, respond_with
from tests.polling import eventually, stays
from tests.task_done import complete_task

PAGE_ID = "page-800"
SEND_API_PATH = "/meta/me/messages"
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
    company_id = create_company(db, "Handoff Co")
    db.execute("update companies set messenger_page_id = %s where id = %s", (PAGE_ID, company_id))
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
    [("pl", "przekaz"), ("en", "pass"), ("ru", "беседу"), ("de", "weiter"), ("uk", "розмову")],
)
def test_client_asking_for_human_gets_handoff_notice_in_own_language(db, fake, meta, client, language, expected):
    respond_with(fake, handoff_reply(reason="Klient prosi o człowieka", language=language))

    meta.post(messenger_payload(PAGE_ID, client, "Chcę rozmawiać z człowiekiem"))

    text = eventually(lambda: sent_texts(fake))[0]
    assert expected in text.lower()
    assert "50 zł" not in text


def test_handoff_notice_for_undetected_language_is_in_company_default_language(db, fake, meta, client, company):
    db.execute("update companies set default_language = 'en' where id = %s", (company,))
    respond_with(fake, handoff_reply(reason="Klient prosi o człowieka", language=None))

    meta.post(messenger_payload(PAGE_ID, client, "Mi volas paroli kun homo"))

    text = eventually(lambda: sent_texts(fake))[0]
    assert "pass" in text.lower()


def handoff_task_id(db):
    row = db.execute("select handoff_task_id from leads").fetchone()
    return row and row[0]


def administrator(crm):
    """Команда администраторов с сотрудником: ей переходник CRM отдаёт Задачу человеку."""
    team_id = crm.add("Team", {"name": "Administratorzy"})["id"]
    crm.add("User", {"userName": "anna", "type": "regular", "isActive": True, "teamsIds": [team_id]})


def hand_off(db, fake, crm, meta, client, *replies):
    """Беседа Клиента передана человеку, в CRM есть Задача человеку; replies — ответы AI после передачи.
    Возвращает id Задачи в CRM."""
    administrator(crm)
    respond_with(fake, handoff_reply(), *replies)
    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje przewóz pianina?"))
    return eventually(lambda: handoff_task_id(db))


def lead_status(db):
    return db.execute("select status from leads").fetchone()[0]


def test_client_message_in_handoff_is_saved_and_left_to_human(db, fake, crm, meta, client):
    hand_off(db, fake, crm, meta, client)

    meta.post(messenger_payload(PAGE_ID, client, "Halo, jest tam ktoś?"))

    eventually(lambda: db.execute("select count(*) from messages where direction = 'in'").fetchone()[0] == 2)
    stays(lambda: len(completion_requests(fake)) == 1 and len(sent_texts(fake)) == 1)
    assert lead_status(db) == "needs_human"


def test_closed_handoff_task_returns_conversation_to_assistant(db, fake, crm, meta, n8n_url, client):
    task_id = hand_off(db, fake, crm, meta, client, assistant_reply(reply="Jak się Pan nazywa?"))

    response = complete_task(n8n_url, task_id)

    assert response.status_code == 200
    assert eventually(lambda: conversation_statuses(db) == ["open"])
    assert lead_status(db) == "collecting"
    meta.post(messenger_payload(PAGE_ID, client, "Dobrze, to chcę zamówić przewóz"))
    assert eventually(lambda: "Jak się Pan nazywa?" in sent_texts(fake))


def test_closed_handoff_task_with_all_required_fields_makes_lead_qualified(db, fake, crm, meta, n8n_url, client):
    administrator(crm)
    respond_with(fake, assistant_reply(intent="booking", lead_data=FULL_LEAD), handoff_reply())
    meta.post(messenger_payload(PAGE_ID, client, "Anna, +48 600 100 200, szafa z IKEA w piątek rano"))
    eventually(lambda: len(sent_texts(fake)) == 1)
    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje przewóz pianina?"))
    task_id = eventually(lambda: handoff_task_id(db))

    complete_task(n8n_url, task_id)

    assert eventually(lambda: lead_status(db) == "qualified")
    assert conversation_statuses(db) == ["open"]


def test_other_closed_task_leaves_conversation_with_human(db, fake, crm, meta, n8n_url, client):
    hand_off(db, fake, crm, meta, client)

    complete_task(n8n_url, "0123456789abcdef0")

    stays(lambda: conversation_statuses(db) == ["handoff"])
    assert lead_status(db) == "needs_human"


def test_closed_task_with_wrong_secret_is_rejected(db, fake, crm, meta, n8n_url, client):
    task_id = hand_off(db, fake, crm, meta, client)

    response = complete_task(n8n_url, task_id, secret="forged")

    assert response.status_code == 401
    stays(lambda: conversation_statuses(db) == ["handoff"])

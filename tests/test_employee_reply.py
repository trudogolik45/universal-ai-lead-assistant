"""Ответ сотрудника из EspoCRM: хук модуля Uala зовёт webhook n8n (контракт — tests/test_espocrm.py),
n8n отправляет текст Клиенту в его Канал, и Ассистент в этой Беседе замолкает.

Главный шов: на входе — подписанный вебхук Meta от Клиента и вебхук хука EspoCRM, на выходе — Send API фейка.
"""

import uuid

import httpx
import pytest

from tests.espocrm import N8N_HOOK_SECRET
from tests.factories import create_company
from tests.meta import MetaClient, messenger_payload, new_mid, new_wamid, whatsapp_payload
from tests.openrouter import assistant_reply, completion_requests, respond_with
from tests.polling import eventually, stays

PAGE_ID = "page-500"
SEND_API_PATH = "/meta/me/messages"
PHONE_NUMBER_ID = "pnid-500"
WHATSAPP_SEND_PATH = f"/meta/{PHONE_NUMBER_ID}/messages"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Employee Co")
    db.execute("update companies set messenger_page_id = %s where id = %s", (PAGE_ID, company_id))
    return company_id


@pytest.fixture
def client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


def employee_reply(n8n_url, sender_id, text, secret=N8N_HOOK_SECRET, channel="messenger") -> httpx.Response:
    """Вызов, который делает хук EspoCRM, когда сотрудник пишет в Беседе."""
    return httpx.post(
        f"{n8n_url}/webhook/employee-reply",
        headers={"X-Uala-Secret": secret},
        json={"crm_message_id": uuid.uuid4().hex[:17], "channel": channel, "sender_id": sender_id, "text": text},
        timeout=10,
    )


def sent_to(fake, sender_id) -> list[dict]:
    return [r.json() for r in fake.requests(SEND_API_PATH) if r.json()["recipient"]["id"] == sender_id]


def client_wrote(fake, meta, sender_id, text="Kiedy auto będzie gotowe?"):
    """Клиент пишет, Ассистент отвечает: Беседа открыта."""
    respond_with(fake, assistant_reply(reply="Sprawdzę i dam znać."))
    meta.post(messenger_payload(PAGE_ID, sender_id, text, new_mid()))
    eventually(lambda: sent_to(fake, sender_id))


def client_last_wrote_hours_ago(db, sender_id, hours):
    db.execute(
        "update messages m set created_at = now() - make_interval(hours => %s)"
        " from conversations c where c.id = m.conversation_id and c.sender_id = %s",
        (hours, sender_id),
    )


def test_employee_reply_is_sent_to_client_in_messenger(n8n_url, fake, meta, client):
    client_wrote(fake, meta, client)

    response = employee_reply(n8n_url, client, "Auto gotowe do odbioru po 16:00.")

    assert response.status_code == 200
    employee_message = {"recipient": {"id": client}, "messaging_type": "RESPONSE", "message": {"text": "Auto gotowe do odbioru po 16:00."}}
    assert eventually(lambda: employee_message in sent_to(fake, client))


def test_assistant_stays_silent_in_conversation_after_employee_replied(n8n_url, fake, meta, client):
    client_wrote(fake, meta, client)
    employee_reply(n8n_url, client, "Dzień dobry, tu Marek z serwisu.")
    eventually(lambda: len(sent_to(fake, client)) == 2)
    answered = len(completion_requests(fake))

    meta.post(messenger_payload(PAGE_ID, client, "Dziękuję, a ile to kosztuje?", new_mid()))

    stays(lambda: len(completion_requests(fake)) == answered and len(sent_to(fake, client)) == 2, seconds=5)


def test_employee_reply_after_24_hours_is_sent_with_human_agent_tag(db, n8n_url, fake, meta, client):
    client_wrote(fake, meta, client)
    client_last_wrote_hours_ago(db, client, 25)

    employee_reply(n8n_url, client, "Przepraszamy za zwłokę, auto jest gotowe.")

    tagged = {
        "recipient": {"id": client},
        "messaging_type": "MESSAGE_TAG",
        "tag": "HUMAN_AGENT",
        "message": {"text": "Przepraszamy za zwłokę, auto jest gotowe."},
    }
    assert eventually(lambda: tagged in sent_to(fake, client))


def test_employee_reply_with_wrong_secret_is_rejected_and_not_sent(n8n_url, fake, meta, client):
    client_wrote(fake, meta, client)

    response = employee_reply(n8n_url, client, "Fałszywa wiadomość", secret="wrong")

    assert response.status_code == 401
    stays(lambda: len(sent_to(fake, client)) == 1)


def test_employee_reply_is_sent_to_client_in_whatsapp(db, n8n_url, fake, meta, company):
    db.execute("update companies set whatsapp_phone_number_id = %s where id = %s", (PHONE_NUMBER_ID, company))
    wa_id = "48" + str(uuid.uuid4().int)[:9]
    respond_with(fake, assistant_reply(reply="Sprawdzę i dam znać."))
    try:
        meta.post(whatsapp_payload(PHONE_NUMBER_ID, wa_id, "Kiedy auto będzie gotowe?", new_wamid()))
        eventually(lambda: fake.requests(WHATSAPP_SEND_PATH))

        employee_reply(n8n_url, wa_id, "Auto gotowe do odbioru po 16:00.", channel="whatsapp")

        employee_message = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa_id,
            "type": "text",
            "text": {"body": "Auto gotowe do odbioru po 16:00."},
        }
        assert eventually(lambda: employee_message in [r.json() for r in fake.requests(WHATSAPP_SEND_PATH)])
    finally:
        db.execute("select delete_client(%s, 'whatsapp', %s)", (company, wa_id))

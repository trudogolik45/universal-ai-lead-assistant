"""Статус ремонта: мастер меняет статус Заказ-наряда в EspoCRM, хук модуля Uala зовёт webhook n8n
(контракт — tests/test_espocrm.py), и Клиент узнаёт, что машину приняли, что ждём запчасти и что можно
забирать. Клиент из WhatsApp получает шаблон WhatsApp, Клиент из Messenger и Instagram — SMS через SMSAPI
(после 24 часов Meta не пускает туда Автоматизации). Закрытие — запрос оценки (tests/test_repair_rating.py),
остальные статусы внутренние.

Главный шов: на входе — вебхук хука EspoCRM, на выходе — WhatsApp Cloud API и SMSAPI фейк-сервера.
"""

import uuid

import pytest

from tests.factories import create_company, open_conversation
from tests.polling import eventually, stays
from tests.reminders import sms_sent
from tests.repair_status import change_status

PHONE_NUMBER_ID = "pnid-300"
WHATSAPP_PATH = f"/meta/{PHONE_NUMBER_ID}/messages"
PHONE = "+48600300300"


@pytest.fixture
def company(db):
    company_id = create_company(db, "AutoPro Service")
    db.execute("update companies set whatsapp_phone_number_id = %s where id = %s", (PHONE_NUMBER_ID, company_id))
    return company_id


def client_in(db, company_id, channel, language="pl") -> dict:
    """Клиент, который писал в Канал и оставил телефон в Заявке; адрес его Беседы — как его шлёт хук."""
    sender_id = "48" + str(uuid.uuid4().int)[:9]
    conversation_id = open_conversation(db, company_id, sender_id=sender_id, channel=channel)
    db.execute("update conversations set language = %s where id = %s", (language, conversation_id))
    db.execute(
        "insert into leads (company_id, conversation_id, phone) values (%s, %s, %s)",
        (company_id, conversation_id, PHONE),
    )
    return {"channel": channel, "sender_id": sender_id}


def whatsapp_sent(fake) -> list[dict]:
    return [r.json() for r in fake.requests(WHATSAPP_PATH)]


@pytest.mark.parametrize(
    ("status", "template"),
    [("Accepted", "repair_accepted"), ("Waiting for Parts", "repair_waiting_for_parts"), ("Ready", "repair_ready")],
)
def test_whatsapp_client_gets_repair_status_template(db, fake, n8n_url, company, status, template):
    client = client_in(db, company, "whatsapp")

    assert change_status(n8n_url, status, [client]).status_code == 200

    [message] = eventually(lambda: whatsapp_sent(fake))
    assert message["to"] == client["sender_id"]
    assert message["template"] == {"name": template, "language": {"code": "pl"}}


@pytest.mark.parametrize(
    ("status", "text"),
    [
        ("Accepted", "AutoPro Service: przyjęliśmy Twój samochód do serwisu."),
        ("Waiting for Parts", "AutoPro Service: czekamy na części do Twojego samochodu. Damy znać, gdy będzie gotowy."),
        ("Ready", "AutoPro Service: Twój samochód jest gotowy do odbioru."),
    ],
)
def test_messenger_client_gets_repair_status_by_sms(db, fake, n8n_url, company, status, text):
    client = client_in(db, company, "messenger")

    change_status(n8n_url, status, [client])

    [sms] = eventually(lambda: sms_sent(fake))
    assert (sms["to"], sms["message"]) == (PHONE.removeprefix("+"), text)
    assert fake.requests("/meta/me/messages") == []


def test_repair_status_language_is_english_for_non_polish_client(db, fake, n8n_url, company):
    client = client_in(db, company, "instagram", language="de")

    change_status(n8n_url, "Ready", [client])

    [sms] = eventually(lambda: sms_sent(fake))
    assert sms["message"] == "AutoPro Service: your car is ready for collection."


@pytest.mark.parametrize("status", ["New", "Diagnostics", "In Repair"])
def test_internal_repair_status_is_not_sent_to_client(db, fake, n8n_url, company, status):
    client = client_in(db, company, "whatsapp")

    assert change_status(n8n_url, status, [client]).status_code == 200

    stays(lambda: whatsapp_sent(fake) == [] and sms_sent(fake) == [], seconds=3)


def test_client_with_several_channels_gets_status_once_in_the_latest_conversation(db, fake, n8n_url, company):
    older = client_in(db, company, "messenger")
    latest = client_in(db, company, "whatsapp")
    db.execute(
        "update conversations set last_message_at = now() - interval '3 days' where sender_id = %s",
        (older["sender_id"],),
    )

    change_status(n8n_url, "Ready", [older, latest])

    [message] = eventually(lambda: whatsapp_sent(fake))
    assert message["to"] == latest["sender_id"]
    stays(lambda: sms_sent(fake) == [] and len(whatsapp_sent(fake)) == 1)


def test_client_without_conversation_gets_nothing(db, fake, n8n_url, company):
    assert change_status(n8n_url, "Ready", []).status_code == 200

    stays(lambda: whatsapp_sent(fake) == [] and sms_sent(fake) == [], seconds=3)


def test_repair_status_with_wrong_secret_is_rejected(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")

    response = change_status(n8n_url, "Ready", [client], secret="wrong")

    assert response.status_code == 401
    stays(lambda: whatsapp_sent(fake) == [])

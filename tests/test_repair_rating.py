"""Отзывы после ремонта: мастер закрывает Заказ-наряд в EspoCRM, Автоматизация один раз просит Клиента
оценить ремонт от 1 до 5. Оценка 4–5 — Клиенту ссылка на отзыв в Google из профиля Заказчика,
1–3 — Задача человеку «разобраться» группе администраторов.

Главный шов: на входе — вебхук хука EspoCRM (закрытие Заказ-наряда) и подписанный вебхук Meta (ответ
Клиента), на выходе — WhatsApp Cloud API, Send API Messenger, SMSAPI и записи фейковой EspoCRM.
"""

import uuid

import pytest

from tests.factories import create_company, open_conversation
from tests.meta import MetaClient, messenger_payload, whatsapp_button_payload, whatsapp_payload
from tests.openrouter import assistant_reply, completion_requests, respond_with
from tests.polling import eventually, stays
from tests.reminders import sms_sent
from tests.repair_status import change_status, new_repair_order_id
from tests.retry import run_retry

PHONE_NUMBER_ID = "pnid-320"
PAGE_ID = "page-320"
WHATSAPP_PATH = f"/meta/{PHONE_NUMBER_ID}/messages"
MESSENGER_PATH = "/meta/me/messages"
PHONE = "+48600320320"
REVIEW_URL = "https://g.page/r/autopro-service/review"
RATING_TEMPLATE = "repair_rating_request"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "AutoPro Service")
    db.execute(
        "update companies set whatsapp_phone_number_id = %s, messenger_page_id = %s, google_review_url = %s"
        " where id = %s",
        (PHONE_NUMBER_ID, PAGE_ID, REVIEW_URL, company_id),
    )
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


def test_closed_repair_order_asks_whatsapp_client_for_rating_template(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")

    assert change_status(n8n_url, "Closed", [client]).status_code == 200

    [message] = eventually(lambda: whatsapp_sent(fake))
    assert message["to"] == client["sender_id"]
    assert message["template"] == {"name": RATING_TEMPLATE, "language": {"code": "pl"}}


def test_rating_is_requested_once_per_repair_order(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")
    repair_order = new_repair_order_id()
    change_status(n8n_url, "Closed", [client], repair_order_id=repair_order)
    eventually(lambda: whatsapp_sent(fake))

    change_status(n8n_url, "In Repair", [client], repair_order_id=repair_order)
    change_status(n8n_url, "Closed", [client], repair_order_id=repair_order)

    stays(lambda: len(whatsapp_sent(fake)) == 1, seconds=4)


def test_messenger_client_is_asked_by_sms_to_reply_with_digit_in_messenger(db, fake, n8n_url, company):
    client = client_in(db, company, "messenger")

    change_status(n8n_url, "Closed", [client])

    [sms] = eventually(lambda: sms_sent(fake))
    assert (sms["to"], sms["message"]) == (
        PHONE.removeprefix("+"),
        "AutoPro Service: dziękujemy za wizytę! Jak oceniasz naprawę w skali od 1 do 5?"
        " Odpisz jedną cyfrą na Messengerze.",
    )


def asked_for_rating(db, fake, n8n_url, company, channel, language="pl") -> dict:
    """Клиент, у которого закрыли Заказ-наряд и попросили оценку; отправленное до ответа забыто
    (сброс фейка чистит и фейковую EspoCRM — сотрудников заводить после)."""
    client = client_in(db, company, channel, language)
    change_status(n8n_url, "Closed", [client])
    eventually(lambda: whatsapp_sent(fake) or sms_sent(fake))
    fake.reset()
    return client


def bad_rating_tasks(crm) -> list[dict]:
    return [t for t in crm.records("Task") if t.get("name", "").startswith("Zła ocena naprawy")]


def administrators(crm) -> tuple[str, str]:
    team = crm.add("Team", {"name": "Administratorzy"})["id"]
    anna = crm.add("User", {"userName": "anna", "type": "regular", "isActive": True, "teamsIds": [team]})["id"]
    return team, anna


def test_good_rating_by_whatsapp_button_gets_google_review_link(db, fake, meta, n8n_url, company):
    client = asked_for_rating(db, fake, n8n_url, company, "whatsapp")

    meta.post(whatsapp_button_payload(PHONE_NUMBER_ID, client["sender_id"], "5"))

    [message] = eventually(lambda: whatsapp_sent(fake))
    assert message["to"] == client["sender_id"]
    assert message["text"]["body"] == (
        f"Dziękujemy za ocenę! Będzie nam bardzo miło, jeśli zostawisz opinię w Google: {REVIEW_URL}"
    )
    assert completion_requests(fake) == []


def test_good_rating_typed_in_messenger_gets_google_review_link_in_english(db, fake, meta, n8n_url, company):
    client = asked_for_rating(db, fake, n8n_url, company, "messenger", language="de")

    meta.post(messenger_payload(PAGE_ID, client["sender_id"], " 4 "))

    [message] = eventually(lambda: [r.json() for r in fake.requests(MESSENGER_PATH)])
    assert message["recipient"] == {"id": client["sender_id"]}
    assert message["message"]["text"] == (
        f"Thank you for your rating! We would be glad if you left us a review on Google: {REVIEW_URL}"
    )


def test_bad_rating_creates_task_for_administrators_and_no_review_link(db, fake, crm, meta, n8n_url, company):
    client = asked_for_rating(db, fake, n8n_url, company, "whatsapp")
    team, anna = administrators(crm)

    meta.post(whatsapp_payload(PHONE_NUMBER_ID, client["sender_id"], "2"))

    [task] = eventually(lambda: bad_rating_tasks(crm))
    assert (task["assignedUserId"], task["teamsIds"], task["parentType"]) == (anna, [team], "Conversation")
    for expected in ("Ocena naprawy: 2/5", "Kanał: WhatsApp", f"Telefon: {PHONE}"):
        assert expected in task["description"]
    [message] = eventually(lambda: whatsapp_sent(fake))
    assert message["text"]["body"] == (
        "Przykro nam, że naprawa nie spełniła oczekiwań. Nasz pracownik wkrótce się z Tobą skontaktuje."
    )
    stays(lambda: len(bad_rating_tasks(crm)) == 1 and completion_requests(fake) == [])


def test_bad_rating_task_not_created_while_crm_failed_is_created_by_retry(db, fake, crm, meta, n8n_url, company):
    client = asked_for_rating(db, fake, n8n_url, company, "whatsapp")
    _, anna = administrators(crm)
    with crm.unavailable("Task"):
        meta.post(whatsapp_payload(PHONE_NUMBER_ID, client["sender_id"], "1"))
        eventually(lambda: fake.requests("/espocrm/api/v1/Task"))
        stays(lambda: bad_rating_tasks(crm) == [])

    db.execute("update repair_ratings set task_claimed_at = now() - interval '10 minutes'")
    run_retry(n8n_url)

    assert eventually(lambda: bad_rating_tasks(crm))[0]["assignedUserId"] == anna
    stays(lambda: len(bad_rating_tasks(crm)) == 1)


def test_digit_from_client_not_asked_for_rating_goes_to_assistant(db, fake, meta, company):
    sender_id = "48" + str(uuid.uuid4().int)[:9]
    respond_with(fake, assistant_reply(reply="Dzień dobry! W czym mogę pomóc?"))

    meta.post(whatsapp_payload(PHONE_NUMBER_ID, sender_id, "5"))

    [message] = eventually(lambda: whatsapp_sent(fake))
    assert message["text"]["body"] == "Dzień dobry! W czym mogę pomóc?"


def test_client_rates_once_and_next_digit_goes_to_assistant(db, fake, meta, n8n_url, company):
    client = asked_for_rating(db, fake, n8n_url, company, "whatsapp")
    meta.post(whatsapp_payload(PHONE_NUMBER_ID, client["sender_id"], "5"))
    eventually(lambda: whatsapp_sent(fake))
    respond_with(fake, assistant_reply(reply="Dziękujemy!"))

    meta.post(whatsapp_payload(PHONE_NUMBER_ID, client["sender_id"], "5"))

    eventually(lambda: len(whatsapp_sent(fake)) == 2)
    assert whatsapp_sent(fake)[1]["text"]["body"] == "Dziękujemy!"
    assert len(completion_requests(fake)) == 1

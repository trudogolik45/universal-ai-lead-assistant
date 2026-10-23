"""Согласие на рекламу, напоминания о ТО и сезонной замене шин.

При Записи Ассистент один раз спрашивает Клиента о Согласии на рекламу, ответ ложится в CRM
(Contact.marketingConsent). Напоминания о ТО (через 11 месяцев после последней Записи) и о сезонной
замене шин уходят только Клиентам с Согласием в CRM; Клиент отказывается — напоминания прекращаются.

Главный шов: подписанный вебхук Meta и ручной запуск рассылки по вебхуку с секретом на входе;
ответы Клиенту, записи фейковой EspoCRM, запросы в WhatsApp Cloud API и SMSAPI на выходе.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.booking import next_weekday, slot, working_calendar
from tests.factories import create_company, open_conversation
from tests.marketing import (
    CONSENT_QUESTION,
    SERVICE_TEMPLATE,
    SUMMER_TYRES_TEMPLATE,
    WINTER_TYRES_TEMPLATE,
    run_marketing,
)
from tests.meta import MetaClient, messenger_payload
from tests.openrouter import assistant_reply, respond_with
from tests.polling import eventually, stays
from tests.reminders import sms_sent

PAGE_ID = "page-330"
PHONE_NUMBER_ID = "pnid-330"
SEND_API_PATH = "/meta/me/messages"
WHATSAPP_PATH = f"/meta/{PHONE_NUMBER_ID}/messages"
CONTACT_PATH = "/espocrm/api/v1/Contact"
PHONE = "+48600330330"
PHONE_GIVEN = {"name": "Jan Kowalski", "phone": PHONE, "vehicle_brand": "Skoda", "vehicle_model": "Octavia"}
BOOKED = "Zapisałem Pana na poniedziałek na 10:00. Do zobaczenia!"
# Дни рассылки: осенью и весной идёт сезон шин, летом — нет.
AUTUMN, SPRING, SUMMER = "2026-10-05", "2026-03-20", "2026-07-01"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "AutoPro Service")
    db.execute(
        "update companies set messenger_page_id = %s, whatsapp_phone_number_id = %s where id = %s",
        (PAGE_ID, PHONE_NUMBER_ID, company_id),
    )
    return company_id


@pytest.fixture
def client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


@pytest.fixture
def calendar(crm):
    return crm.add("WorkingTimeCalendar", working_calendar())


def replies(fake, sender_id) -> list[str]:
    return [
        r.json()["message"]["text"] for r in fake.requests(SEND_API_PATH) if r.json()["recipient"]["id"] == sender_id
    ]


def say(fake, meta, sender_id, text, *ai_replies):
    """Сообщение Клиента с ответом AI; ждём, пока Ассистент ответит."""
    respond_with(fake, *ai_replies)
    before = len(replies(fake, sender_id))
    meta.post(messenger_payload(PAGE_ID, sender_id, text))
    return eventually(lambda: len(replies(fake, sender_id)) > before and replies(fake, sender_id)[-1])


def book_visit(fake, meta, sender_id):
    """Клиент даёт телефон и записывается в слот; возвращает ответ на Запись."""
    say(fake, meta, sender_id, "Jan Kowalski, 600 330 330, Skoda Octavia", assistant_reply(lead_data=PHONE_GIVEN))
    start = slot(next_weekday(0), 10)
    return say(fake, meta, sender_id, "Poniedziałek 10:00", assistant_reply(BOOKED, intent="booking", appointment_start=start))


def client_contact(crm, sender_id) -> dict | None:
    """Клиент в CRM — через его Беседу в Канале."""
    for conversation in crm.records("Conversation"):
        if conversation["senderId"] == sender_id and conversation.get("contactId"):
            return next(c for c in crm.records("Contact") if c["id"] == conversation["contactId"])
    return None


def consent_in_crm(crm, sender_id):
    contact = client_contact(crm, sender_id)
    return contact.get("marketingConsent") if contact else None


def close_conversation(db, sender_id):
    db.execute("update conversations set status = 'closed' where sender_id = %s", (sender_id,))


def test_assistant_asks_marketing_consent_when_client_books(fake, crm, meta, client, calendar):
    reply = book_visit(fake, meta, client)

    assert reply == f"{BOOKED}\n\n{CONSENT_QUESTION['pl']}"


def test_assistant_asks_marketing_consent_when_lead_is_complete_without_calendar(fake, crm, meta, client):
    reply = say(fake, meta, client, "Jan Kowalski, 600 330 330, Skoda Octavia, wymiana oleju w piątek", assistant_reply(
        "Dziękuję, przekażę zgłoszenie.", language="en", qualified=True,
        lead_data={**PHONE_GIVEN, "service": "Wymiana oleju", "contact": "jan@example.com"},
    ))

    assert reply == f"Dziękuję, przekażę zgłoszenie.\n\n{CONSENT_QUESTION['en']}"


def test_marketing_consent_is_asked_only_once_per_client(db, fake, crm, meta, client, calendar):
    book_visit(fake, meta, client)
    again = say(fake, meta, client, "Dziękuję", assistant_reply("Do zobaczenia!", lead_data=PHONE_GIVEN, qualified=True))
    close_conversation(db, client)
    say(fake, meta, client, "Dzień dobry, znowu ja", assistant_reply(lead_data=PHONE_GIVEN))
    start = slot(next_weekday(1), 10)
    second_booking = say(fake, meta, client, "Wtorek 10:00", assistant_reply(BOOKED, intent="booking", appointment_start=start))

    assert again == "Do zobaczenia!"
    assert second_booking == BOOKED


def test_client_consent_is_stored_in_crm(fake, crm, meta, client, calendar):
    book_visit(fake, meta, client)

    say(fake, meta, client, "Tak", assistant_reply("Dziękuję!", lead_data=PHONE_GIVEN, marketing_consent=True))

    assert eventually(lambda: consent_in_crm(crm, client) is True)


def test_client_who_writes_stop_withdraws_consent_in_crm(fake, crm, meta, client, calendar):
    book_visit(fake, meta, client)
    say(fake, meta, client, "Tak", assistant_reply("Dziękuję!", lead_data=PHONE_GIVEN, marketing_consent=True))
    eventually(lambda: consent_in_crm(crm, client) is True)

    # AI не понял отказ — STOP всё равно отзывает Согласие.
    say(fake, meta, client, "STOP", assistant_reply("Rozumiem.", lead_data=PHONE_GIVEN))

    assert eventually(lambda: consent_in_crm(crm, client) is False)


# --- Рассылка -------------------------------------------------------------------------------------


def known_client(db, crm, company_id, channel="whatsapp", consent=True, last_visit=None, language="pl"):
    """Клиент, который уже писал: Беседа и Заявка с телефоном в Postgres, Клиент и Беседа в CRM;
    last_visit — начало его последней Записи."""
    sender_id = "48" + str(uuid.uuid4().int)[:9]
    conversation_id = open_conversation(db, company_id, sender_id=sender_id, channel=channel)
    db.execute("update conversations set language = %s where id = %s", (language, conversation_id))
    lead_id = db.execute(
        "insert into leads (company_id, conversation_id, phone) values (%s, %s, %s) returning id",
        (company_id, conversation_id, PHONE),
    ).fetchone()[0]
    if last_visit:
        db.execute(
            "insert into appointments (company_id, lead_id, starts_at, ends_at, crm_meeting_id)"
            " values (%s, %s, %s, %s, %s)",
            (company_id, lead_id, last_visit, last_visit + timedelta(hours=1), uuid.uuid4().hex[:17]),
        )
    contact = crm.add("Contact", {"lastName": "Kowalski", "marketingConsent": consent})
    crm.add("Conversation", {
        "name": f"{channel} · {sender_id}", "channel": channel, "senderId": sender_id, "contactId": contact["id"],
    })
    return sender_id


def visit_before(day: str, months: int) -> datetime:
    return datetime.fromisoformat(day).replace(hour=9, tzinfo=timezone.utc) - timedelta(days=30.5 * months)


def whatsapp_sent(fake) -> list[dict]:
    return [r.json() for r in fake.requests(WHATSAPP_PATH)]


def templates_sent(fake, sender_id) -> list[tuple[str, str]]:
    return [
        (m["template"]["name"], m["template"]["language"]["code"]) for m in whatsapp_sent(fake) if m["to"] == sender_id
    ]


def run_and_settle(n8n_url, fake, today):
    """Запуск рассылки; ждём, пока он прочитает Клиентов CRM и дойдёт до отправки."""
    before = len(fake.requests(CONTACT_PATH))
    assert run_marketing(n8n_url, today).status_code == 200
    eventually(lambda: len(fake.requests(CONTACT_PATH)) > before)


def test_consented_client_gets_winter_tyres_reminder_in_autumn(db, fake, crm, n8n_url, company):
    sender_id = known_client(db, crm, company)

    assert run_marketing(n8n_url, AUTUMN).status_code == 200

    assert eventually(lambda: templates_sent(fake, sender_id)) == [(WINTER_TYRES_TEMPLATE, "pl")]


def test_consented_client_gets_summer_tyres_reminder_in_spring(db, fake, crm, n8n_url, company):
    sender_id = known_client(db, crm, company, language="de")

    run_marketing(n8n_url, SPRING)

    assert eventually(lambda: templates_sent(fake, sender_id)) == [(SUMMER_TYRES_TEMPLATE, "en")]


def test_consented_client_gets_service_reminder_eleven_months_after_last_visit(db, fake, crm, n8n_url, company):
    due = known_client(db, crm, company, last_visit=visit_before(SUMMER, months=12))
    recent = known_client(db, crm, company, last_visit=visit_before(SUMMER, months=6))

    run_marketing(n8n_url, SUMMER)

    assert eventually(lambda: templates_sent(fake, due)) == [(SERVICE_TEMPLATE, "pl")]
    run_and_settle(n8n_url, fake, SUMMER)
    assert templates_sent(fake, recent) == []


def test_client_without_consent_gets_no_reminders(db, fake, crm, n8n_url, company):
    known_client(db, crm, company, consent=False, last_visit=visit_before(AUTUMN, months=12))

    run_and_settle(n8n_url, fake, AUTUMN)

    stays(lambda: whatsapp_sent(fake) == [] and sms_sent(fake) == [], seconds=3)


def test_no_tyres_reminder_out_of_season(db, fake, crm, n8n_url, company):
    known_client(db, crm, company)

    run_and_settle(n8n_url, fake, SUMMER)

    stays(lambda: whatsapp_sent(fake) == [], seconds=3)


def test_each_reminder_is_sent_once(db, fake, crm, n8n_url, company):
    sender_id = known_client(db, crm, company)
    run_marketing(n8n_url, AUTUMN)
    eventually(lambda: templates_sent(fake, sender_id))

    run_and_settle(n8n_url, fake, "2026-10-06")

    stays(lambda: len(templates_sent(fake, sender_id)) == 1, seconds=3)


@pytest.mark.parametrize("channel, where", [("messenger", "Messengerze"), ("instagram", "Instagramie")])
def test_client_from_messenger_or_instagram_gets_reminder_by_sms(db, fake, crm, n8n_url, company, channel, where):
    known_client(db, crm, company, channel=channel)

    run_marketing(n8n_url, AUTUMN)

    [sms] = eventually(lambda: sms_sent(fake))
    assert sms["to"] == PHONE.removeprefix("+")
    assert sms["message"] == (
        "AutoPro Service: zbliża się sezon opon zimowych — zapraszamy na wymianę. "
        f"Nie chcesz takich przypomnień? Napisz STOP na {where}."
    )
    assert fake.requests(SEND_API_PATH) == []


def test_client_who_refused_gets_no_more_reminders(db, fake, crm, meta, n8n_url, company):
    """Клиент из Messenger ответил на напоминание STOP: следующий сезон ему уже ничего не шлёт."""
    sender_id = known_client(db, crm, company, channel="messenger")
    run_marketing(n8n_url, AUTUMN)
    eventually(lambda: sms_sent(fake))

    say(fake, meta, sender_id, "STOP", assistant_reply("Rozumiem."))
    eventually(lambda: consent_in_crm(crm, sender_id) is False)
    run_and_settle(n8n_url, fake, SPRING)

    stays(lambda: len(sms_sent(fake)) == 1, seconds=3)


def test_manual_run_without_secret_is_rejected(n8n_url):
    assert run_marketing(n8n_url, secret="wrong").status_code == 401

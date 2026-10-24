"""Напоминания о Записи за 24 и за 2 часа: Клиент из WhatsApp получает шаблон WhatsApp на pl или en,
Клиент из Messenger и Instagram — SMS через SMSAPI (после 24 часов Meta не пускает туда Автоматизации).
Каждый срок напоминается один раз, отменённая Запись (Meeting Not Held) не напоминается.

Главный шов: Запись в фейковой EspoCRM и в Postgres, ручной запуск по вебхуку с секретом на входе;
запросы в WhatsApp Cloud API и SMSAPI фейк-сервера на выходе.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.factories import create_company, open_conversation
from tests.fake_server import Response
from tests.polling import eventually, stays
from tests.reminders import REMINDER_TEMPLATE, SMS_PATH, SMSAPI_TOKEN, espo_time, in_hours, run_reminders, sms_sent

PHONE_NUMBER_ID = "pnid-290"
WHATSAPP_PATH = f"/meta/{PHONE_NUMBER_ID}/messages"
PHONE = "+48600290290"
WARSAW = ZoneInfo("Europe/Warsaw")


@dataclass
class Booking:
    sender_id: str
    meeting_id: str
    starts_at: datetime


@pytest.fixture
def company(db):
    company_id = create_company(db, "AutoPro Service")
    db.execute("update companies set whatsapp_phone_number_id = %s where id = %s", (PHONE_NUMBER_ID, company_id))
    return company_id


def book(db, crm, company_id, channel, starts_at, booked_ago=timedelta(days=3), language="pl"):
    """Запись Клиента: Meeting в CRM и строка appointments, как их оставляет онлайн-запись (#28)."""
    sender_id = "48" + str(uuid.uuid4().int)[:9]
    conversation_id = open_conversation(db, company_id, sender_id=sender_id, channel=channel)
    db.execute("update conversations set language = %s where id = %s", (language, conversation_id))
    lead_id = db.execute(
        "insert into leads (company_id, conversation_id, phone) values (%s, %s, %s) returning id",
        (company_id, conversation_id, PHONE),
    ).fetchone()[0]
    meeting = crm.add("Meeting", {
        "name": "Wizyta", "status": "Planned",
        "dateStart": espo_time(starts_at), "dateEnd": espo_time(starts_at + timedelta(hours=1)),
    })
    db.execute(
        "insert into appointments (company_id, lead_id, starts_at, ends_at, crm_meeting_id, created_at)"
        " values (%s, %s, %s, %s, %s, now() - %s)",
        (company_id, lead_id, starts_at, starts_at + timedelta(hours=1), meeting["id"], booked_ago),
    )
    return Booking(sender_id, meeting["id"], starts_at)


def whatsapp_sent(fake) -> list[dict]:
    return [r.json() for r in fake.requests(WHATSAPP_PATH)]


def local(starts_at):
    moment = starts_at.astimezone(WARSAW)
    return moment.strftime("%d.%m.%Y"), moment.strftime("%H:%M")


def run_and_settle(n8n_url, fake):
    """Запуск напоминаний; ждём, пока он прочитает Записи CRM и дойдёт до отправки."""
    before = len(fake.requests("/espocrm/api/v1/Meeting"))
    assert run_reminders(n8n_url).status_code == 200
    eventually(lambda: len(fake.requests("/espocrm/api/v1/Meeting")) > before)


def test_whatsapp_client_gets_reminder_template_a_day_before(db, fake, crm, n8n_url, company):
    booking = book(db, crm, company, "whatsapp", in_hours(20))

    assert run_reminders(n8n_url).status_code == 200

    [message] = eventually(lambda: whatsapp_sent(fake))
    day, time = local(booking.starts_at)
    assert message["to"] == booking.sender_id
    assert message["template"] == {
        "name": REMINDER_TEMPLATE,
        "language": {"code": "pl"},
        "components": [{"type": "body", "parameters": [
            {"type": "text", "text": day}, {"type": "text", "text": time},
        ]}],
    }


def test_each_deadline_is_reminded_once(db, fake, crm, n8n_url, company):
    booking = book(db, crm, company, "whatsapp", in_hours(20))
    run_reminders(n8n_url)
    eventually(lambda: len(whatsapp_sent(fake)) == 1)
    run_and_settle(n8n_url, fake)
    stays(lambda: len(whatsapp_sent(fake)) == 1)

    # Прошло 18 часов: до Записи меньше двух.
    crm.change("Meeting", booking.meeting_id, {"dateStart": espo_time(in_hours(1.5))})
    run_reminders(n8n_url)
    eventually(lambda: len(whatsapp_sent(fake)) == 2)
    run_and_settle(n8n_url, fake)

    stays(lambda: len(whatsapp_sent(fake)) == 2)


@pytest.mark.parametrize("channel", ["messenger", "instagram"])
def test_client_without_whatsapp_gets_reminder_by_sms(db, fake, crm, n8n_url, company, channel):
    booking = book(db, crm, company, channel, in_hours(1.5))

    run_reminders(n8n_url)

    [sms] = eventually(lambda: sms_sent(fake))
    day, time = local(booking.starts_at)
    assert sms["to"] == PHONE.removeprefix("+")
    assert sms["message"] == f"AutoPro Service: przypominamy o wizycie {day} o godz. {time}."
    assert (sms["encoding"], sms["format"]) == ("utf-8", "json")
    assert sms["authorization"] == f"Bearer {SMSAPI_TOKEN}"
    assert whatsapp_sent(fake) == [] and fake.requests("/meta/me/messages") == []


def test_reminder_language_is_english_for_non_polish_client(db, fake, crm, n8n_url, company):
    booking = book(db, crm, company, "messenger", in_hours(20), language="de")

    run_reminders(n8n_url)

    [sms] = eventually(lambda: sms_sent(fake))
    day, time = local(booking.starts_at)
    assert sms["message"] == f"AutoPro Service: reminder of your appointment on {day} at {time}."


def test_cancelled_appointment_is_not_reminded(db, fake, crm, n8n_url, company):
    booking = book(db, crm, company, "whatsapp", in_hours(20))
    crm.change("Meeting", booking.meeting_id, {"status": "Not Held"})

    run_and_settle(n8n_url, fake)

    stays(lambda: whatsapp_sent(fake) == [], seconds=3)


def test_deadline_passed_before_booking_is_not_reminded(db, fake, crm, n8n_url, company):
    book(db, crm, company, "whatsapp", in_hours(20), booked_ago=timedelta(hours=1))

    run_and_settle(n8n_url, fake)

    stays(lambda: whatsapp_sent(fake) == [], seconds=3)


def test_failed_sms_is_sent_by_next_run(db, fake, crm, n8n_url, company):
    book(db, crm, company, "messenger", in_hours(20))
    fake.respond("POST", SMS_PATH, Response(200, {"error": 101, "message": "Authorization failed"}), Response(200, {"count": 1}))
    run_reminders(n8n_url)
    eventually(lambda: len(sms_sent(fake)) == 1)
    run_and_settle(n8n_url, fake)
    stays(lambda: len(sms_sent(fake)) == 1)

    # Повтор берёт неотправленное через 5 минут после попытки.
    db.execute("update appointment_reminders set claimed_at = now() - interval '10 minutes'")
    run_reminders(n8n_url)

    eventually(lambda: len(sms_sent(fake)) == 2)
    run_and_settle(n8n_url, fake)
    stays(lambda: len(sms_sent(fake)) == 2)


def test_manual_run_without_secret_is_rejected(n8n_url):
    assert run_reminders(n8n_url, secret="wrong").status_code == 401

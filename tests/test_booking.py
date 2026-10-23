"""Запись в свободный слот: Ассистент получает свободные слоты по рабочему календарю Заказчика
и Записям (Meeting) в EspoCRM и сам ставит Запись — Meeting, связанный с Клиентом и Автомобилем.
Без телефона Записи нет, два Клиента в один слот не попадают. Нет календаря — время не подтверждается.

Главный шов: подписанный вебхук Meta на входе; запрос к AI (какие слоты ему дали), ответ Клиенту
и записи фейковой EspoCRM (tests/fake_espocrm.py) на выходе.
"""

import threading
import uuid

import pytest

from tests.booking import (
    meeting,
    next_weekday,
    offered_slots,
    slot,
    system_prompt,
    utc,
    working_calendar,
)
from tests.factories import create_company
from tests.marketing import CONSENT_QUESTION
from tests.meta import MetaClient, messenger_payload
from tests.openrouter import assistant_reply, completion_requests, respond_with
from tests.polling import eventually, stays

PAGE_ID = "page-280"
SEND_API_PATH = "/meta/me/messages"
PHONE_GIVEN = {"name": "Jan Kowalski", "phone": "+48600123456", "vehicle_brand": "Skoda", "vehicle_model": "Octavia"}
BOOKED = "Zapisałem Pana na poniedziałek na 10:00. Do zobaczenia!"
# Ответ о Записи уходит с вопросом о Согласии на рекламу: Клиента спрашивают один раз (#33).
BOOKED_REPLY = f"{BOOKED}\n\n{CONSENT_QUESTION['pl']}"
# Ответ Клиенту, чей слот только что занял другой (узел «Booking result» в handle-message).
SLOT_TAKEN = "Przepraszam, ten termin został właśnie zajęty. Proszę wybrać inny wolny termin."


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Booking Co")
    db.execute("update companies set messenger_page_id = %s where id = %s", (PAGE_ID, company_id))
    return company_id


def new_client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


@pytest.fixture
def client(db, company):
    yield from new_client(db, company)


@pytest.fixture
def other_client(db, company):
    yield from new_client(db, company)


@pytest.fixture
def calendar(crm):
    return crm.add("WorkingTimeCalendar", working_calendar())


def replies(fake, sender_id) -> list[str]:
    return [
        r.json()["message"]["text"] for r in fake.requests(SEND_API_PATH) if r.json()["recipient"]["id"] == sender_id
    ]


def say(fake, meta, sender_id, text):
    """Сообщение Клиента; ждём, пока Ассистент ответит."""
    before = len(replies(fake, sender_id))
    meta.post(messenger_payload(PAGE_ID, sender_id, text))
    return eventually(lambda: len(replies(fake, sender_id)) > before and replies(fake, sender_id)[-1])


def give_phone(fake, meta, sender_id):
    respond_with(fake, assistant_reply(lead_data=PHONE_GIVEN))
    say(fake, meta, sender_id, "Jan Kowalski, 600 123 456, Skoda Octavia")


def book(fake, start):
    respond_with(fake, assistant_reply(BOOKED, intent="booking", appointment_start=start))


def test_free_slots_follow_working_hours_and_skip_booked_meetings(fake, crm, meta, client, calendar):
    monday, saturday, sunday = next_weekday(0), next_weekday(5), next_weekday(6)
    crm.add("Meeting", meeting(slot(monday, 10)))
    crm.add("Meeting", meeting(slot(monday, 12), status="Not Held"))
    give_phone(fake, meta, client)

    say(fake, meta, client, "Kiedy mogę przyjechać?")

    slots = offered_slots(fake)
    assert slot(monday, 10) not in slots
    assert {slot(monday, 8), slot(monday, 9), slot(monday, 11), slot(monday, 12), slot(monday, 17)} <= set(slots)
    assert slot(monday, 18) not in slots and slot(monday, 7) not in slots
    assert {slot(saturday, 9), slot(saturday, 13)} <= set(slots) and slot(saturday, 14) not in slots
    assert not [s for s in slots if s.startswith(sunday.isoformat())]
    assert f"{monday.isoformat()} (Monday)" in system_prompt(fake)


def test_non_working_day_of_calendar_has_no_slots(fake, crm, meta, client, calendar):
    tuesday = next_weekday(1)
    crm.add("WorkingTimeRange", {
        "type": "Non-working", "dateStart": tuesday.isoformat(), "dateEnd": tuesday.isoformat(),
        "calendarsIds": [calendar["id"]],
    })
    give_phone(fake, meta, client)

    say(fake, meta, client, "Kiedy mogę przyjechać?")

    assert not [s for s in offered_slots(fake) if s.startswith(tuesday.isoformat())]


def test_client_is_booked_into_free_slot_as_meeting_of_client_and_vehicle(fake, crm, meta, client, calendar):
    start = slot(next_weekday(0), 10)
    give_phone(fake, meta, client)
    book(fake, start)

    reply = say(fake, meta, client, "Tak, poniedziałek 10:00 pasuje")

    assert reply == BOOKED_REPLY
    [booked] = crm.records("Meeting")
    assert (booked["dateStart"], booked["dateEnd"], booked["status"]) == (utc(start), utc(start, 1), "Planned")
    [contact] = eventually(lambda: crm.records("Contact"))
    [vehicle] = eventually(lambda: crm.records("Vehicle"))
    [linked] = eventually(lambda: [m for m in crm.records("Meeting") if m.get("vehicleId")])
    assert (linked["contactsIds"], linked["vehicleId"]) == ([contact["id"]], vehicle["id"])
    # Канал Записи — для отчётов владельцу.
    assert linked["channel"] == "messenger"


def test_booked_client_is_not_booked_again(fake, crm, meta, client, calendar):
    start = slot(next_weekday(0), 10)
    give_phone(fake, meta, client)
    book(fake, start)
    say(fake, meta, client, "Tak, poniedziałek 10:00 pasuje")
    respond_with(fake, assistant_reply("Do zobaczenia w poniedziałek!"))

    say(fake, meta, client, "Dziękuję!")

    assert offered_slots(fake) == []
    assert start in system_prompt(fake)
    assert len(crm.records("Meeting")) == 1


def test_without_phone_assistant_asks_for_number_before_booking(fake, crm, meta, client, calendar):
    respond_with(fake, assistant_reply("Proszę podać numer telefonu.", lead_data={"name": "Jan Kowalski"}))

    say(fake, meta, client, "Chcę się zapisać na poniedziałek na 10")

    assert offered_slots(fake) == []
    assert "ask for it before booking" in system_prompt(fake)
    stays(lambda: crm.records("Meeting") == [])


def test_without_calendar_assistant_does_not_confirm_time(fake, crm, meta, client):
    give_phone(fake, meta, client)

    say(fake, meta, client, "Chcę się zapisać na poniedziałek na 10")

    assert offered_slots(fake) == []
    assert "Never confirm a booking" in system_prompt(fake)
    assert crm.records("Meeting") == []


def test_two_clients_do_not_get_the_same_slot(fake, crm, meta, client, other_client, calendar):
    start = slot(next_weekday(0), 10)
    give_phone(fake, meta, client)
    give_phone(fake, meta, other_client)
    book(fake, start)

    threads = [
        threading.Thread(target=meta.post, args=(messenger_payload(PAGE_ID, sender, "Poniedziałek 10:00"),))
        for sender in (client, other_client)
    ]
    # CRM думает над поиском Записей: оба Клиента проверяют слот, пока ни одна Запись ещё не создана.
    with crm.slow("Meeting", 3):
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        eventually(lambda: all(len(replies(fake, sender)) == 2 for sender in (client, other_client)), timeout=60)
    assert sorted(replies(fake, sender)[1] for sender in (client, other_client)) == sorted([BOOKED_REPLY, SLOT_TAKEN])
    assert len(crm.records("Meeting")) == 1
    assert len(completion_requests(fake)) == 4

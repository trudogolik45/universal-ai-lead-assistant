"""Заявка в CRM: по ходу Беседы n8n пишет в EspoCRM Заявку (Lead), Клиента (Contact) и Автомобиль
(Vehicle) через переходник CRM. Клиент находится по Каналу и отправителю — через его Беседу в CRM.
Недоступная CRM не теряет Заявку: retry дописывает её после восстановления.

Главный шов: подписанный вебхук Meta на входе, записи фейковой EspoCRM (tests/fake_espocrm.py) на выходе.
"""

import uuid

import pytest

from tests.factories import create_company
from tests.meta import MetaClient, messenger_payload, whatsapp_payload
from tests.openrouter import assistant_reply, respond_with
from tests.polling import eventually, stays
from tests.retry import run_retry

PAGE_ID = "page-500"
PHONE_NUMBER_ID = "pnid-500"
SEND_API_PATH = "/meta/me/messages"
LEAD_PATH = "/espocrm/api/v1/Lead"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Crm Lead Co")
    db.execute("update companies set messenger_page_id = %s where id = %s", (PAGE_ID, company_id))
    return company_id


@pytest.fixture
def client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


def conversation(crm, sender_id, channel="messenger"):
    found = [c for c in crm.records("Conversation") if (c["channel"], c["senderId"]) == (channel, sender_id)]
    return found[0] if len(found) == 1 else None


def client_leads(crm, sender_id, channel="messenger"):
    found = conversation(crm, sender_id, channel)
    return crm.related("Conversation", found["id"], "leads") if found else []


def lead_fields(lead):
    return {
        key: lead.get(key)
        for key in ("firstName", "lastName", "phoneNumber", "service", "description", "desiredTime")
    }


def replies_sent(fake):
    return fake.requests(SEND_API_PATH)


def close_conversation(db, sender_id):
    db.execute("update conversations set status = 'closed' where sender_id = %s", (sender_id,))


def crm_lead_write_stale(db, minutes=10):
    """Запись Заявки в CRM начата minutes назад: retry дописывает только то, что уже не в работе."""
    db.execute("update crm_leads set claimed_at = now() - make_interval(mins => %s)", (minutes,))


def test_lead_is_written_to_crm_with_client_found_by_channel_and_sender(fake, crm, meta, client):
    respond_with(fake, assistant_reply(
        intent="booking",
        lead_data={
            "name": "Jan Kowalski",
            "phone": "+48600123456",
            "service": "Diagnostyka zawieszenia",
            "description": "Stuki w zawieszeniu przy hamowaniu",
            "desired_date": "jutro po 16:00",
        },
    ))

    meta.post(messenger_payload(PAGE_ID, client, "Jan Kowalski, 600 123 456, stuka w zawieszeniu, jutro po 16"))

    [lead] = eventually(lambda: client_leads(crm, client))
    assert lead_fields(lead) == {
        "firstName": "Jan",
        "lastName": "Kowalski",
        "phoneNumber": "+48600123456",
        "service": "Diagnostyka zawieszenia",
        "description": "Stuki w zawieszeniu przy hamowaniu",
        "desiredTime": "jutro po 16:00",
    }
    [contact] = crm.records("Contact")
    assert (contact["firstName"], contact["lastName"], contact["phoneNumber"]) == ("Jan", "Kowalski", "+48600123456")
    assert conversation(crm, client)["contactId"] == contact["id"]
    assert lead["contactId"] == contact["id"]


def test_lead_and_vehicle_are_updated_as_conversation_goes_on(fake, crm, meta, client):
    respond_with(
        fake,
        assistant_reply(lead_data={"name": "Anna Nowak", "vehicle_brand": "Skoda"}),
        assistant_reply(lead_data={"vehicle_model": "Octavia", "desired_date": "w piątek rano"}),
    )
    meta.post(messenger_payload(PAGE_ID, client, "Anna Nowak, mam Skodę"))
    eventually(lambda: client_leads(crm, client) and crm.records("Vehicle"))

    meta.post(messenger_payload(PAGE_ID, client, "Octavia, w piątek rano"))

    eventually(lambda: [v["model"] for v in crm.records("Vehicle")] == ["Octavia"])
    [lead] = eventually(lambda: [x for x in client_leads(crm, client) if x.get("desiredTime") == "w piątek rano"])
    [vehicle] = crm.records("Vehicle")
    assert (vehicle["name"], vehicle["brand"], vehicle["model"]) == ("Skoda Octavia", "Skoda", "Octavia")
    [contact] = crm.records("Contact")
    assert vehicle["contactId"] == contact["id"]
    assert lead["vehicleId"] == vehicle["id"]
    assert (lead["firstName"], lead["lastName"]) == ("Anna", "Nowak")
    assert len(crm.records("Lead")) == 1


def test_whatsapp_client_phone_is_taken_from_number_when_not_given(db, fake, crm, meta, company):
    db.execute("update companies set whatsapp_phone_number_id = %s where id = %s", (PHONE_NUMBER_ID, company))
    wa_id = "48" + str(uuid.uuid4().int)[:9]
    respond_with(fake, assistant_reply(lead_data={"name": "Jan Kowalski", "service": "Wymiana oleju"}))

    try:
        meta.post(whatsapp_payload(PHONE_NUMBER_ID, wa_id, "Jan Kowalski, wymiana oleju"))

        [lead] = eventually(lambda: client_leads(crm, wa_id, "whatsapp"))
        assert lead["phoneNumber"] == f"+{wa_id}"
    finally:
        db.execute("select delete_client(%s, 'whatsapp', %s)", (company, wa_id))


def test_returning_client_gets_new_lead_but_stays_the_same_client_in_crm(db, fake, crm, meta, client):
    respond_with(
        fake,
        assistant_reply(lead_data={"name": "Piotr Zieliński", "service": "Wymiana oleju"}),
        assistant_reply(lead_data={"service": "Wymiana opon"}),
    )
    meta.post(messenger_payload(PAGE_ID, client, "Piotr Zieliński, wymiana oleju"))
    eventually(lambda: client_leads(crm, client))
    close_conversation(db, client)

    meta.post(messenger_payload(PAGE_ID, client, "Teraz opony"))

    leads = eventually(lambda: len(client_leads(crm, client)) == 2 and client_leads(crm, client))
    assert sorted(lead["service"] for lead in leads) == ["Wymiana oleju", "Wymiana opon"]
    [contact] = crm.records("Contact")
    assert {lead["contactId"] for lead in leads} == {contact["id"]}


def test_unknown_name_and_phone_without_country_code_do_not_block_lead(fake, crm, meta, client):
    respond_with(fake, assistant_reply(lead_data={"phone": "600 123 456", "vehicle_model": "Corolla"}))

    meta.post(messenger_payload(PAGE_ID, client, "600 123 456, Corolla"))

    [lead] = eventually(lambda: client_leads(crm, client))
    assert lead["lastName"] == f"messenger · {client}"
    assert lead.get("phoneNumber") is None
    [vehicle] = crm.records("Vehicle")
    assert (vehicle["name"], vehicle["model"]) == ("Corolla", "Corolla")


def test_unavailable_crm_does_not_lose_lead_and_retry_writes_it_after_recovery(db, fake, crm, meta, n8n_url, client):
    respond_with(fake, assistant_reply(lead_data={"name": "Jan Kowalski", "service": "Wymiana oleju"}))
    # Лежит только запись Заявок: без Базы знаний из CRM Ассистент молчал бы и Заявку не обновлял (#23).
    with crm.unavailable("Lead"):
        meta.post(messenger_payload(PAGE_ID, client, "Jan Kowalski, wymiana oleju"))
        eventually(lambda: fake.requests(LEAD_PATH))
        stays(lambda: crm.records("Lead") == [])

    crm_lead_write_stale(db)
    run_retry(n8n_url)

    [lead] = eventually(lambda: client_leads(crm, client))
    assert (lead["lastName"], lead["service"]) == ("Kowalski", "Wymiana oleju")
    assert len(crm.records("Contact")) == 1


def test_retry_does_not_write_lead_already_in_crm_again(db, fake, crm, meta, n8n_url, client):
    respond_with(fake, assistant_reply(lead_data={"name": "Jan Kowalski"}))
    meta.post(messenger_payload(PAGE_ID, client, "Jan Kowalski"))
    eventually(lambda: client_leads(crm, client))
    writes = len(fake.requests(LEAD_PATH))

    crm_lead_write_stale(db)
    run_retry(n8n_url)

    stays(lambda: len(fake.requests(LEAD_PATH)) == writes, seconds=5)

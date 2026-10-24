"""Смета: машину приняли — мастер получает Задачу человеку «составить Смету»; готовая Смета сама уходит
Клиенту; Клиент молчит — цепочка уточнений, после неё Задача человеку; ответ Клиента цепочку останавливает.

Главный шов: на входе — вебхуки хуков EspoCRM (статус Заказ-наряда, статус Сметы; контракт —
tests/test_espocrm.py) и ручной запуск цепочки по вебхуку с секретом retry; на выходе — записи фейковой
EspoCRM, WhatsApp Cloud API и SMSAPI фейк-сервера.
"""

import uuid

import pytest

from tests.estimates import change_estimate_status, run_estimates
from tests.factories import add_message, create_company, open_conversation
from tests.polling import eventually, stays
from tests.reminders import sms_sent
from tests.repair_status import change_status, new_repair_order_id

PHONE_NUMBER_ID = "pnid-310"
WHATSAPP_PATH = f"/meta/{PHONE_NUMBER_ID}/messages"
PHONE = "+48600310310"
MECHANICS = "Mechanicy"
ADMINISTRATORS = "Administratorzy"
READY_PL = "AutoPro Service: kosztorys naprawy „Wymiana sprzęgła” jest gotowy: 1250,50 PLN. Odpisz nam, czy go akceptujesz."
REMINDER_PL = "AutoPro Service: przypominamy o kosztorysie naprawy „Wymiana sprzęgła”: 1250,50 PLN. Odpisz nam, czy go akceptujesz."


@pytest.fixture
def company(db):
    company_id = create_company(db, "AutoPro Service")
    db.execute("update companies set whatsapp_phone_number_id = %s where id = %s", (PHONE_NUMBER_ID, company_id))
    return company_id


def team(crm, name):
    return crm.add("Team", {"name": name})["id"]


def employee(crm, user_name, team_id, open_tasks=0):
    user = crm.add("User", {"userName": user_name, "type": "regular", "isActive": True, "teamsIds": [team_id]})
    for _ in range(open_tasks):
        crm.add("Task", {"name": "Wcześniejsze zadanie", "status": "Started", "assignedUserId": user["id"]})
    return user["id"]


def repair_order_tasks(crm, order_id):
    return [t for t in crm.records("Task") if t.get("parentType") == "RepairOrder" and t.get("parentId") == order_id]


def client_in(db, company_id, channel, language="pl") -> dict:
    """Клиент, который писал в Канал и оставил телефон в Заявке; адрес его Беседы — как его шлёт хук."""
    sender_id = "48" + str(uuid.uuid4().int)[:9]
    conversation_id = open_conversation(db, company_id, sender_id=sender_id, channel=channel)
    db.execute("update conversations set language = %s where id = %s", (language, conversation_id))
    db.execute(
        "insert into leads (company_id, conversation_id, phone) values (%s, %s, %s)",
        (company_id, conversation_id, PHONE),
    )
    return {"channel": channel, "sender_id": sender_id, "conversation_id": conversation_id}


def address(client) -> dict:
    return {"channel": client["channel"], "sender_id": client["sender_id"]}


def whatsapp_sent(fake) -> list[dict]:
    return [r.json() for r in fake.requests(WHATSAPP_PATH)]


def template(name, amount="1250,50 PLN", language="pl"):
    return {
        "name": name,
        "language": {"code": language},
        "components": [{"type": "body", "parameters": [
            {"type": "text", "text": "Wymiana sprzęgła"}, {"type": "text", "text": amount},
        ]}],
    }


def days_pass(db, estimate_id, days):
    """Сдвигает сделанные шаги цепочки в прошлое: будто с них прошло days суток."""
    db.execute(
        "update estimate_steps set done_at = done_at - %s * interval '1 day',"
        " claimed_at = claimed_at - %s * interval '1 day' where crm_estimate_id = %s",
        (days, days, estimate_id),
    )


def estimate_sent(db, fake, n8n_url, client, **kwargs) -> str:
    """Готовая Смета ушла Клиенту из WhatsApp; возвращает id Сметы. Фейк (и его CRM) после неё пуст."""
    estimate_id = uuid.uuid4().hex[:17]
    change_estimate_status(n8n_url, "Ready", [address(client)], estimate_id=estimate_id, **kwargs)
    eventually(lambda: whatsapp_sent(fake))
    eventually(lambda: step_done(db, estimate_id, "sent"))
    fake.reset()
    return estimate_id


def step_done(db, estimate_id, step) -> bool:
    return db.execute(
        "select 1 from estimate_steps where crm_estimate_id = %s and step = %s and done_at is not null",
        (estimate_id, step),
    ).fetchone() is not None


def run_and_settle(db, n8n_url, estimate_id, step):
    assert run_estimates(n8n_url).status_code == 200
    eventually(lambda: step_done(db, estimate_id, step))


# --- Задача «составить Смету» ---


def test_accepted_car_gives_least_busy_mechanic_task_to_compose_estimate(fake, crm, n8n_url, company):
    mechanics = team(crm, MECHANICS)
    employee(crm, "marek", mechanics, open_tasks=2)
    piotr = employee(crm, "piotr", mechanics)
    employee(crm, "anna", team(crm, ADMINISTRATORS))
    order_id = new_repair_order_id()

    response = change_status(n8n_url, "Accepted", [], repair_order_id=order_id, name="Skoda Octavia: wymiana sprzęgła")

    assert response.status_code == 200
    [task] = eventually(lambda: repair_order_tasks(crm, order_id))
    assert task["name"] == "Kosztorys: Skoda Octavia: wymiana sprzęgła"
    assert (task["status"], task["assignedUserId"], task["teamsIds"]) == ("Not Started", piotr, [mechanics])


def test_car_accepted_again_gives_no_second_estimate_task(fake, crm, n8n_url, company):
    employee(crm, "piotr", team(crm, MECHANICS))
    order_id = new_repair_order_id()
    change_status(n8n_url, "Accepted", [], repair_order_id=order_id)
    eventually(lambda: repair_order_tasks(crm, order_id))

    change_status(n8n_url, "Diagnostics", [], repair_order_id=order_id)
    change_status(n8n_url, "Accepted", [], repair_order_id=order_id)

    stays(lambda: len(repair_order_tasks(crm, order_id)) == 1, seconds=3)


@pytest.mark.parametrize("status", ["New", "Diagnostics", "Ready"])
def test_other_repair_status_gives_no_estimate_task(fake, crm, n8n_url, company, status):
    employee(crm, "piotr", team(crm, MECHANICS))
    order_id = new_repair_order_id()

    assert change_status(n8n_url, status, [], repair_order_id=order_id).status_code == 200

    stays(lambda: repair_order_tasks(crm, order_id) == [], seconds=3)


# --- Готовая Смета Клиенту ---


def test_ready_estimate_goes_to_whatsapp_client_as_template_with_name_and_amount(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")

    response = change_estimate_status(n8n_url, "Ready", [address(client)])

    assert response.status_code == 200
    [message] = eventually(lambda: whatsapp_sent(fake))
    assert message["to"] == client["sender_id"]
    assert message["template"] == template("estimate_ready")


def test_ready_estimate_goes_to_messenger_client_by_sms(db, fake, n8n_url, company):
    client = client_in(db, company, "messenger")

    change_estimate_status(n8n_url, "Ready", [address(client)])

    [sms] = eventually(lambda: sms_sent(fake))
    assert (sms["to"], sms["message"]) == (PHONE.removeprefix("+"), READY_PL)


def test_estimate_is_in_english_for_non_polish_client(db, fake, n8n_url, company):
    client = client_in(db, company, "instagram", language="de")

    change_estimate_status(n8n_url, "Ready", [address(client)], amount=980)

    [sms] = eventually(lambda: sms_sent(fake))
    assert sms["message"] == (
        'AutoPro Service: the repair estimate "Wymiana sprzęgła" is ready: 980.00 PLN. Please reply whether you accept it.'
    )


def test_draft_estimate_is_not_sent(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")

    assert change_estimate_status(n8n_url, "Draft", [address(client)]).status_code == 200

    stays(lambda: whatsapp_sent(fake) == [] and sms_sent(fake) == [], seconds=3)


def test_estimate_status_with_wrong_secret_is_rejected(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")

    response = change_estimate_status(n8n_url, "Ready", [address(client)], secret="wrong")

    assert response.status_code == 401
    stays(lambda: whatsapp_sent(fake) == [])


# --- Цепочка уточнений ---


def test_silent_client_gets_no_reminder_before_a_day_passes(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")
    estimate_id = estimate_sent(db, fake, n8n_url, client)
    days_pass(db, estimate_id, 0.9)

    assert run_estimates(n8n_url).status_code == 200

    stays(lambda: whatsapp_sent(fake) == [], seconds=3)


def test_silent_client_gets_reminder_a_day_after_estimate(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")
    estimate_id = estimate_sent(db, fake, n8n_url, client)
    days_pass(db, estimate_id, 1)

    run_and_settle(db, n8n_url, estimate_id, "reminder_1")

    [message] = whatsapp_sent(fake)
    assert (message["to"], message["template"]) == (client["sender_id"], template("estimate_reminder"))


def test_silent_messenger_client_gets_reminder_by_sms(db, fake, n8n_url, company):
    client = client_in(db, company, "messenger")
    estimate_id = uuid.uuid4().hex[:17]
    change_estimate_status(n8n_url, "Ready", [address(client)], estimate_id=estimate_id)
    eventually(lambda: step_done(db, estimate_id, "sent"))
    fake.reset()
    days_pass(db, estimate_id, 1)

    run_and_settle(db, n8n_url, estimate_id, "reminder_1")

    assert [sms["message"] for sms in sms_sent(fake)] == [REMINDER_PL]


def test_silent_client_gets_two_reminders_then_administrator_gets_task(db, fake, crm, n8n_url, company):
    client = client_in(db, company, "whatsapp")
    order_id = uuid.uuid4().hex[:17]
    estimate_id = estimate_sent(db, fake, n8n_url, client, order_id=order_id)
    administrators = team(crm, ADMINISTRATORS)
    anna = employee(crm, "anna", administrators)
    employee(crm, "piotr", team(crm, MECHANICS))

    for step in ("reminder_1", "reminder_2"):
        days_pass(db, estimate_id, 2)
        run_and_settle(db, n8n_url, estimate_id, step)
    days_pass(db, estimate_id, 2)
    run_and_settle(db, n8n_url, estimate_id, "silent_task")

    assert [m["template"]["name"] for m in whatsapp_sent(fake)] == ["estimate_reminder", "estimate_reminder"]
    [task] = repair_order_tasks(crm, order_id)
    assert task["name"] == "Klient milczy po kosztorysie: Wymiana sprzęgła"
    assert "1250,50 PLN" in task["description"]
    assert f"WhatsApp · {client['sender_id']}" in task["description"]
    assert (task["status"], task["assignedUserId"], task["teamsIds"]) == ("Not Started", anna, [administrators])


def test_second_reminder_waits_two_days_after_first(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")
    estimate_id = estimate_sent(db, fake, n8n_url, client)
    days_pass(db, estimate_id, 1)
    run_and_settle(db, n8n_url, estimate_id, "reminder_1")
    days_pass(db, estimate_id, 1)

    assert run_estimates(n8n_url).status_code == 200

    stays(lambda: len(whatsapp_sent(fake)) == 1, seconds=3)


def test_chain_is_over_after_silent_client_task(db, fake, crm, n8n_url, company):
    client = client_in(db, company, "whatsapp")
    order_id = uuid.uuid4().hex[:17]
    estimate_id = estimate_sent(db, fake, n8n_url, client, order_id=order_id)
    employee(crm, "anna", team(crm, ADMINISTRATORS))
    for step in ("reminder_1", "reminder_2", "silent_task"):
        days_pass(db, estimate_id, 2)
        run_and_settle(db, n8n_url, estimate_id, step)
    days_pass(db, estimate_id, 30)

    assert run_estimates(n8n_url).status_code == 200

    stays(lambda: len(whatsapp_sent(fake)) == 2 and len(repair_order_tasks(crm, order_id)) == 1, seconds=3)


def test_client_reply_stops_chain(db, fake, crm, n8n_url, company):
    client = client_in(db, company, "whatsapp")
    order_id = uuid.uuid4().hex[:17]
    estimate_id = estimate_sent(db, fake, n8n_url, client, order_id=order_id)
    employee(crm, "anna", team(crm, ADMINISTRATORS))
    add_message(db, company, client["conversation_id"])

    for _ in range(3):
        days_pass(db, estimate_id, 2)
        assert run_estimates(n8n_url).status_code == 200

    stays(lambda: whatsapp_sent(fake) == [] and repair_order_tasks(crm, order_id) == [], seconds=3)


def test_client_reply_in_new_conversation_of_same_channel_stops_chain(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")
    estimate_id = estimate_sent(db, fake, n8n_url, client)
    db.execute("update conversations set status = 'closed' where id = %s", (client["conversation_id"],))
    newer = open_conversation(db, company, sender_id=client["sender_id"], channel="whatsapp")
    add_message(db, company, newer)
    days_pass(db, estimate_id, 1)

    assert run_estimates(n8n_url).status_code == 200

    stays(lambda: whatsapp_sent(fake) == [], seconds=3)


@pytest.mark.parametrize("status", ["Accepted", "Rejected", "Draft"])
def test_estimate_status_changed_by_employee_stops_chain(db, fake, n8n_url, company, status):
    client = client_in(db, company, "whatsapp")
    estimate_id = estimate_sent(db, fake, n8n_url, client)

    change_estimate_status(n8n_url, status, [address(client)], estimate_id=estimate_id)
    eventually(lambda: db.execute(
        "select stopped_at from estimates where crm_estimate_id = %s", (estimate_id,)
    ).fetchone()[0])
    days_pass(db, estimate_id, 1)

    assert run_estimates(n8n_url).status_code == 200

    stays(lambda: whatsapp_sent(fake) == [], seconds=3)


def test_estimate_ready_again_after_revision_is_sent_again(db, fake, n8n_url, company):
    client = client_in(db, company, "whatsapp")
    estimate_id = estimate_sent(db, fake, n8n_url, client)
    change_estimate_status(n8n_url, "Draft", [address(client)], estimate_id=estimate_id)

    change_estimate_status(n8n_url, "Ready", [address(client)], estimate_id=estimate_id, amount=1100)

    [message] = eventually(lambda: whatsapp_sent(fake))
    assert message["template"] == template("estimate_ready", amount="1100,00 PLN")


def test_unsent_estimate_is_sent_by_next_run(db, fake, n8n_url, company):
    client = client_in(db, company, "messenger")
    db.execute("update leads set phone = null where conversation_id = %s", (client["conversation_id"],))
    estimate_id = uuid.uuid4().hex[:17]
    change_estimate_status(n8n_url, "Ready", [address(client)], estimate_id=estimate_id)
    stays(lambda: sms_sent(fake) == [], seconds=3)
    db.execute("update leads set phone = %s where conversation_id = %s", (PHONE, client["conversation_id"]))
    db.execute("update estimate_steps set claimed_at = now() - interval '10 minutes'")

    run_and_settle(db, n8n_url, estimate_id, "sent")

    assert [sms["message"] for sms in sms_sent(fake)] == [READY_PL]


def test_manual_run_with_wrong_secret_is_rejected(db, fake, n8n_url, company):
    assert run_estimates(n8n_url, secret="wrong").status_code == 401

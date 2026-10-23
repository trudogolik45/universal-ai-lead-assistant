"""Задача человеку в CRM при Передаче человеку: Task со ссылкой на Беседу и сводкой на польском
уходит группе администраторов, внутри группы — сотруднику с наименьшим числом открытых задач.

Главный шов: подписанный вебхук Meta на входе, записи фейковой EspoCRM (tests/fake_espocrm.py) на выходе.
"""

import uuid

import pytest

from tests.factories import create_company
from tests.meta import MetaClient, messenger_payload
from tests.openrouter import assistant_reply, completion_requests, respond_with
from tests.polling import eventually, stays
from tests.retry import run_retry

PAGE_ID = "page-240"
TASK_PATH = "/espocrm/api/v1/Task"
# Группа, которой n8n отдаёт Передачу человеку (команда EspoCRM, её заводит scripts/espocrm_bootstrap.py).
ADMINISTRATORS = "Administratorzy"


@pytest.fixture
def meta(n8n_url):
    return MetaClient(n8n_url)


@pytest.fixture
def company(db):
    company_id = create_company(db, "Task Co")
    db.execute("update companies set messenger_page_id = %s where id = %s", (PAGE_ID, company_id))
    return company_id


@pytest.fixture
def client(db, company):
    sender_id = f"psid-{uuid.uuid4().hex[:8]}"
    yield sender_id
    db.execute("select delete_client(%s, 'messenger', %s)", (company, sender_id))


def team(crm, name):
    return crm.add("Team", {"name": name})["id"]


def employee(crm, user_name, team_id, open_tasks=0, closed_tasks=0, active=True):
    user = crm.add("User", {"userName": user_name, "type": "regular", "isActive": active, "teamsIds": [team_id]})
    for status in ["Started"] * open_tasks + ["Completed"] * closed_tasks:
        crm.add("Task", {"name": "Wcześniejsze zadanie", "status": status, "assignedUserId": user["id"]})
    return user["id"]


def handoff_reply(reason="Klient pyta o cenę spoza bazy wiedzy"):
    return assistant_reply(reply="Cena to 50 zł.", needs_human=True, handoff_reason=reason)


def handoff_tasks(crm):
    return [t for t in crm.records("Task") if t.get("parentType") == "Conversation"]


def client_conversation(crm, sender_id):
    return next(c for c in crm.records("Conversation") if c["senderId"] == sender_id)


def test_handoff_creates_task_linked_to_conversation_with_polish_summary(fake, crm, meta, client):
    administrators = team(crm, ADMINISTRATORS)
    anna = employee(crm, "anna", administrators)
    respond_with(fake, handoff_reply())

    meta.post(messenger_payload(PAGE_ID, client, "Ile kosztuje wymiana sprzęgła w Audi A4?"))

    task = eventually(lambda: handoff_tasks(crm))[0]
    assert (task["parentType"], task["parentId"]) == ("Conversation", client_conversation(crm, client)["id"])
    assert task["name"].startswith("Przekazanie rozmowy")
    for expected in ("Powód: Klient pyta o cenę spoza bazy wiedzy", "Ile kosztuje wymiana sprzęgła w Audi A4?"):
        assert expected in task["description"]
    assert (task["status"], task["assignedUserId"], task["teamsIds"]) == ("Not Started", anna, [administrators])


def test_handoff_task_goes_to_least_busy_active_administrator(fake, crm, meta, client):
    administrators = team(crm, ADMINISTRATORS)
    mechanics = team(crm, "Mechanicy")
    employee(crm, "anna", administrators, open_tasks=2)
    beata = employee(crm, "beata", administrators, open_tasks=1, closed_tasks=5)
    employee(crm, "celina", administrators, active=False)
    employee(crm, "marek", mechanics)
    respond_with(fake, handoff_reply())

    meta.post(messenger_payload(PAGE_ID, client, "Chcę rozmawiać z człowiekiem"))

    assert eventually(lambda: handoff_tasks(crm))[0]["assignedUserId"] == beata


def test_assistant_stays_silent_in_handed_off_conversation_and_no_second_task(fake, crm, meta, client):
    employee(crm, "anna", team(crm, ADMINISTRATORS))
    respond_with(fake, handoff_reply())
    meta.post(messenger_payload(PAGE_ID, client, "Chcę rozmawiać z człowiekiem"))
    eventually(lambda: handoff_tasks(crm))

    meta.post(messenger_payload(PAGE_ID, client, "Halo, jest tam ktoś?"))

    eventually(lambda: any(m["text"] == "Halo, jest tam ktoś?" for m in crm.records("Message")))
    stays(lambda: len(completion_requests(fake)) == 1 and len(handoff_tasks(crm)) == 1)


def test_task_not_created_while_crm_failed_is_created_by_retry(db, fake, crm, meta, n8n_url, client):
    anna = employee(crm, "anna", team(crm, ADMINISTRATORS))
    respond_with(fake, handoff_reply())
    with crm.unavailable("Task"):
        meta.post(messenger_payload(PAGE_ID, client, "Chcę rozmawiać z człowiekiem"))
        eventually(lambda: fake.requests(TASK_PATH))
        stays(lambda: handoff_tasks(crm) == [])

    db.execute("update leads set handoff_task_claimed_at = now() - interval '10 minutes'")
    run_retry(n8n_url)

    assert eventually(lambda: handoff_tasks(crm))[0]["assignedUserId"] == anna
    stays(lambda: len(handoff_tasks(crm)) == 1)

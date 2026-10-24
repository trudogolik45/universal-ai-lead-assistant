"""Контрактные тесты на втором шве: настоящая EspoCRM стенда. Их несколько, не больше (спека #17):
сущности и поля модуля Uala есть, API-пользователь n8n пишет и читает то, что пишет и читает
переходник CRM, хуки модуля зовут n8n. Остальное поведение — на главном шве с фейком EspoCRM.

Образ с модулем Uala (deploy/espocrm), Postgres стенда и API-пользователь n8n
(scripts/espocrm_bootstrap.py) — те же, что в проде. Фикстура `espocrm` — tests/conftest.py.
"""

import json
import socket
import uuid

from scripts.espocrm import EspoCrm
from scripts.espocrm_bootstrap import API_USER
from tests.booking import WORKING_CALENDAR_NODE, WORKING_RANGES_NODE, adapter_query, busy_where
from tests.espocrm import EMPLOYEE_REPLY_PATH, ESTIMATE_PATH, N8N_HOOK_SECRET, REPAIR_STATUS_PATH, TASK_DONE_PATH
from tests.fake_server import Response
from tests.knowledge import assistant_knowledge_query
from tests.marketing import consented_where, conversations_of_where
from tests.owner_report import report_where
from tests.polling import eventually, stays
from tests.reminders import planned_where

EMPLOYEE_PASSWORD = "test-employee-1"
# Хук повторяет вызов n8n: в стенде пауза между попытками — секунда, задания запускает daemon раз в 10 с.
RETRY_TIMEOUT = 150


def create_conversation(espocrm, sender_id: str, channel: str = "messenger") -> dict:
    client = espocrm.api.create("Contact", {"firstName": "Jan", "lastName": "Kowalski"})
    return espocrm.api.create(
        "Conversation",
        {"name": f"Jan Kowalski · {channel}", "channel": channel, "senderId": sender_id, "contactId": client["id"]},
    )


def employee(espocrm, team_name: str, open_tasks: int = 0) -> dict:
    """Сотрудник Заказчика в команде (группе): его заводит администратор CRM."""
    team = espocrm.admin.find("Team", [{"type": "equals", "attribute": "name", "value": team_name}])[0]
    user = espocrm.admin.create(
        "User",
        {
            "userName": f"{team_name.lower()}-{uuid.uuid4().hex[:6]}",
            "lastName": "Kowalska",
            "type": "regular",
            "isActive": True,
            "password": EMPLOYEE_PASSWORD,
            "passwordConfirm": EMPLOYEE_PASSWORD,
            "teamsIds": [team["id"]],
        },
    )
    for _ in range(open_tasks):
        espocrm.admin.create("Task", {"name": "Wcześniejsze zadanie", "status": "Started", "assignedUserId": user["id"]})
    return user


def logged_in(espocrm, user: dict) -> EspoCrm:
    return EspoCrm(espocrm.url, admin=(user["userName"], EMPLOYEE_PASSWORD))


def find_ids(client, entity: str, where: list[dict], **params) -> list[str]:
    return [record["id"] for record in client.find(entity, where, select=["id"], **params)]


def notifications(client) -> list[dict]:
    """Уведомления CRM сотруднику (колокольчик)."""
    return client.request("GET", "Notification", params={"maxSize": 50})["list"]


def test_api_user_writes_conversation_and_messages_in_sent_order(espocrm):
    wanted = create_conversation(espocrm, "psid-200")
    create_conversation(espocrm, "psid-201")
    [found] = espocrm.api.find(
        "Conversation",
        [
            {"type": "equals", "attribute": "channel", "value": "messenger"},
            {"type": "equals", "attribute": "senderId", "value": "psid-200"},
        ],
        select=["id"],
        maxSize=1,
    )

    # retry дописывает пропущенное позже: в Беседе Сообщения встают по времени отправки, не записи.
    for direction, author, text, sent_at in (
        ("out", "assistant", "Wymiana oleju — 150 zł.", "2026-10-23 10:00:07"),
        ("in", "client", "Ile kosztuje wymiana oleju?", "2026-10-23 10:00:01"),
    ):
        espocrm.api.create(
            "Message",
            {"conversationId": found["id"], "direction": direction, "author": author, "text": text, "sentAt": sent_at},
        )

    messages = espocrm.api.related("Conversation", wanted["id"], "messages")
    assert [(m["direction"], m["author"], m["text"]) for m in messages] == [
        ("in", "client", "Ile kosztuje wymiana oleju?"),
        ("out", "assistant", "Wymiana oleju — 150 zł."),
    ]


def test_api_user_writes_client_lead_vehicle_and_appointment(espocrm):
    conversation = create_conversation(espocrm, "psid-210")
    client_id = conversation["contactId"]
    vehicle = espocrm.api.create("Vehicle", {"name": "Skoda Octavia", "brand": "Skoda", "model": "Octavia",
                                             "contactId": client_id})

    lead = espocrm.api.create(
        "Lead",
        {
            "firstName": "Jan", "lastName": "Kowalski", "phoneNumber": "+48600123456", "channel": "messenger",
            "description": "Stuki w zawieszeniu", "service": "Diagnostyka zawieszenia", "desiredTime": "jutro po 16:00",
            "contactId": client_id, "vehicleId": vehicle["id"], "conversationId": conversation["id"],
        },
    )
    # Запись Ассистента — без исполнителя: мастера назначает сервис.
    meeting = espocrm.api.create(
        "Meeting", {"name": "Wizyta: Jan Kowalski", "dateStart": "2031-03-04 09:00:00", "dateEnd": "2031-03-04 10:00:00"}
    )
    espocrm.api.update("Meeting", meeting["id"], {"contactsIds": [client_id], "vehicleId": vehicle["id"]})

    read = espocrm.api.read("Lead", lead["id"])
    assert (read["service"], read["desiredTime"], read["phoneNumber"]) == (
        "Diagnostyka zawieszenia", "jutro po 16:00", "+48600123456"
    )
    for entity, record_id in (("Contact", client_id), ("Vehicle", vehicle["id"]), ("Conversation", conversation["id"])):
        assert [r["id"] for r in espocrm.api.related(entity, record_id, "leads")] == [lead["id"]]
    assert espocrm.api.read("Meeting", meeting["id"])["status"] == "Planned"
    assert [m["id"] for m in espocrm.api.related("Vehicle", vehicle["id"], "meetings")] == [meeting["id"]]


def test_api_user_reads_knowledge_base_and_working_calendar_as_assistant_does(espocrm):
    item = espocrm.admin.create(
        "KnowledgeItem",
        {"name": "Wymiana klocków (kontrakt)", "kind": "service", "description": "Jedna oś.", "price": 140,
         "priceFrom": True},
    )
    calendar = espocrm.admin.create(
        "WorkingTimeCalendar",
        {"name": "Aaa kontrakt", "timeZone": "Europe/Warsaw", "timeRanges": [["8:00", "18:00"]], "weekday6": True},
    )
    espocrm.admin.create(
        "WorkingTimeRange",
        {"type": "Non-working", "dateStart": "2031-12-24", "dateEnd": "2031-12-26", "calendarsIds": [calendar["id"]]},
    )

    knowledge = espocrm.api.request("GET", "KnowledgeItem", params=assistant_knowledge_query())["list"]
    [found] = espocrm.api.request("GET", "WorkingTimeCalendar", params=adapter_query(WORKING_CALENDAR_NODE))["list"]
    ranges = espocrm.api.request(
        "GET", f"WorkingTimeCalendar/{calendar['id']}/ranges", params=adapter_query(WORKING_RANGES_NODE)
    )["list"]
    espocrm.admin.request("DELETE", f"WorkingTimeCalendar/{calendar['id']}")

    [read] = [k for k in knowledge if k["id"] == item["id"]]
    assert (read["kind"], read["price"], read["priceFrom"]) == ("service", 140, True)
    assert (found["id"], found["timeRanges"], found["weekday0"], found["weekday6"]) == (
        calendar["id"], [["8:00", "18:00"]], False, True
    )
    assert [(r["type"], r["dateStart"]) for r in ranges] == [("Non-working", "2031-12-24")]
    assert espocrm.api.http.post("KnowledgeItem", json={"name": "Olej za 1 zł", "kind": "service"}).status_code == 403


def test_api_user_finds_meetings_and_clients_as_crm_adapter_does(espocrm):
    booked = espocrm.api.create(
        "Meeting", {"name": "Wizyta", "dateStart": "2031-03-03 09:00:00", "dateEnd": "2031-03-03 10:00:00"}
    )
    espocrm.api.update("Meeting", booked["id"], {"channel": "call"})
    espocrm.api.create(
        "Meeting",
        {"name": "Odwołana", "dateStart": "2031-03-03 10:00:00", "dateEnd": "2031-03-03 11:00:00", "status": "Not Held"},
    )
    agreed = espocrm.api.create("Contact", {"lastName": "Zgoda", "marketingConsent": True})
    espocrm.api.create("Conversation", {"name": "whatsapp · 48600333001", "channel": "whatsapp",
                                        "senderId": "48600333001", "contactId": agreed["id"]})

    busy = find_ids(espocrm.api, "Meeting", busy_where("2031-03-03 09:30:00", "2031-03-03 10:30:00"), maxSize=200)
    planned = find_ids(espocrm.api, "Meeting", planned_where("2031-03-03 08:00:00", "2031-03-04 08:00:00"), maxSize=200)
    called = espocrm.api.request("GET", "Meeting", params={"searchParams": json.dumps(
        {"where": report_where("2000-01-01 00:00:00", "2100-01-01 00:00:00", "call"), "select": ["id"], "maxSize": 1}
    )})
    consented = find_ids(espocrm.api, "Contact", consented_where(), maxSize=200)
    addresses = espocrm.api.find("Conversation", conversations_of_where(consented), select=["channel", "senderId"],
                                 maxSize=200)

    assert busy == [booked["id"]] and planned == [booked["id"]]
    assert called["total"] >= 1
    assert ("whatsapp", "48600333001") in {(a["channel"], a["senderId"]) for a in addresses}


def test_handoff_task_goes_to_team_member_and_notifies_them(espocrm):
    conversation = create_conversation(espocrm, "psid-240")
    busy = employee(espocrm, "Administratorzy", open_tasks=2)
    team_id = busy["teamsIds"][0]

    members = find_ids(
        espocrm.api, "User",
        [{"type": "linkedWith", "attribute": "teams", "value": [team_id]},
         {"type": "equals", "attribute": "isActive", "value": True}],
        orderBy="userName", order="asc", maxSize=200,
    )
    open_tasks = espocrm.api.request("GET", "Task", params={"searchParams": json.dumps({
        "where": [{"type": "equals", "attribute": "assignedUserId", "value": busy["id"]},
                  {"type": "in", "attribute": "status", "value": ["Not Started", "Started"]}],
        "select": ["id"], "maxSize": 1,
    })})
    task = espocrm.api.create(
        "Task",
        {"name": "Przekazanie rozmowy: Jan Kowalski", "status": "Not Started", "parentType": "Conversation",
         "parentId": conversation["id"], "assignedUserId": busy["id"], "teamsIds": [team_id]},
    )

    assert busy["id"] in members and open_tasks["total"] == 2
    assert [t["id"] for t in espocrm.api.related("Conversation", conversation["id"], "tasks")] == [task["id"]]
    assert eventually(lambda: task["id"] in [n["relatedParentId"] for n in notifications(logged_in(espocrm, busy))])


def employee_replies(fake) -> list:
    return fake.requests(EMPLOYEE_REPLY_PATH)


def test_employee_message_calls_n8n_and_messages_of_n8n_do_not(espocrm, fake):
    conversation = create_conversation(espocrm, "psid-400")
    as_employee = logged_in(espocrm, employee(espocrm, "Administratorzy"))
    espocrm.api.create(
        "Message", {"conversationId": conversation["id"], "direction": "out", "author": "assistant", "text": "Dzień dobry."}
    )

    # Сотрудник пишет из Беседы: направление и автора не выбирает.
    message = as_employee.create("Message", {"conversationId": conversation["id"], "text": "Auto gotowe do odbioru."})

    [call] = eventually(lambda: employee_replies(fake))
    assert call.headers["X-Uala-Secret"] == N8N_HOOK_SECRET
    assert call.json() == {
        "crm_message_id": message["id"],
        "channel": "messenger",
        "sender_id": "psid-400",
        "text": "Auto gotowe do odbioru.",
    }
    saved = espocrm.admin.read("Message", message["id"])
    assert (saved["direction"], saved["author"], bool(saved["sentAt"])) == ("out", "employee", True)
    stays(lambda: len(employee_replies(fake)) == 1)


def repair_order(espocrm) -> tuple[dict, list[dict]]:
    """Заказ-наряд Клиента, который писал в Messenger и WhatsApp; возвращает его и Беседы Клиента."""
    client = espocrm.api.create("Contact", {"firstName": "Jan", "lastName": "Kowalski"})
    conversations = [
        {"channel": channel, "sender_id": f"{channel}-{uuid.uuid4().hex[:8]}"} for channel in ("messenger", "whatsapp")
    ]
    for c in conversations:
        espocrm.api.create("Conversation", {"name": f"Jan Kowalski · {c['channel']}", "channel": c["channel"],
                                            "senderId": c["sender_id"], "contactId": client["id"]})
    order = espocrm.admin.create("RepairOrder", {"name": "Skoda Octavia: sprzęgło", "contactId": client["id"]})
    return order, conversations


def calls(fake, path: str, key: str, record_id: str) -> list[dict]:
    return [r.json() for r in fake.requests(path) if r.json()[key] == record_id]


def test_closed_task_and_new_repair_and_estimate_status_call_n8n(espocrm, fake):
    mechanic = employee(espocrm, "Mechanicy")
    as_mechanic = logged_in(espocrm, mechanic)
    task = espocrm.api.create("Task", {"name": "Przekazanie", "status": "Not Started", "parentType": "Conversation",
                                       "parentId": create_conversation(espocrm, "psid-420")["id"],
                                       "assignedUserId": mechanic["id"]})
    order, conversations = repair_order(espocrm)
    estimate = espocrm.admin.create(
        "Estimate", {"name": "Wymiana sprzęgła", "repairOrderId": order["id"], "amount": 1250.5, "amountCurrency": "PLN"}
    )
    eventually(lambda: calls(fake, ESTIMATE_PATH, "crm_estimate_id", estimate["id"]))
    fake.reset()

    espocrm.admin.update("RepairOrder", order["id"], {"description": "Bez zmiany statusu"})
    as_mechanic.update("Task", task["id"], {"status": "Completed"})
    as_mechanic.update("RepairOrder", order["id"], {"status": "Waiting for Parts"})
    as_mechanic.update("Estimate", estimate["id"], {"status": "Ready"})

    assert eventually(lambda: calls(fake, TASK_DONE_PATH, "crm_task_id", task["id"])) == [{"crm_task_id": task["id"]}]
    [status] = eventually(lambda: calls(fake, REPAIR_STATUS_PATH, "crm_repair_order_id", order["id"]))
    assert (status["status"], status["name"]) == ("Waiting for Parts", "Skoda Octavia: sprzęgło")
    assert sorted(status["conversations"], key=lambda c: c["channel"]) == conversations
    [ready] = eventually(lambda: calls(fake, ESTIMATE_PATH, "crm_estimate_id", estimate["id"]))
    assert (ready["status"], ready["crm_repair_order_id"], ready["amount"], ready["currency"]) == (
        "Ready", order["id"], 1250.5, "PLN"
    )
    assert sorted(ready["conversations"], key=lambda c: c["channel"]) == conversations


def test_hook_repeats_call_until_n8n_accepts_it(espocrm, fake):
    """n8n лежит или отвечает ошибкой: ответ сотрудника не теряется, хук повторяет вызов."""
    fake.respond("POST", EMPLOYEE_REPLY_PATH, Response(500), Response(401), Response(200))
    conversation = create_conversation(espocrm, "psid-430")
    as_employee = logged_in(espocrm, employee(espocrm, "Administratorzy"))

    message = as_employee.create("Message", {"conversationId": conversation["id"], "text": "Części już są."})

    attempts = eventually(lambda: len(employee_replies(fake)) >= 3 and employee_replies(fake), timeout=RETRY_TIMEOUT)
    assert {r.json()["crm_message_id"] for r in attempts} == {message["id"]}
    stays(lambda: len(employee_replies(fake)) == 3, seconds=25)


def test_employee_learns_from_crm_that_n8n_never_accepted_the_message(espocrm, fake):
    fake.respond("POST", EMPLOYEE_REPLY_PATH, Response(503))
    conversation = create_conversation(espocrm, "psid-440")
    as_employee = logged_in(espocrm, employee(espocrm, "Administratorzy"))

    message = as_employee.create("Message", {"conversationId": conversation["id"], "text": "Zapraszamy jutro."})

    [notice] = eventually(
        lambda: [n for n in notifications(as_employee) if n["relatedId"] == message["id"]], timeout=RETRY_TIMEOUT
    )
    assert (notice["type"], notice["relatedType"]) == ("Message", "Message")
    assert "klient" in notice["message"].lower()


def test_n8n_works_as_api_user_and_websocket_is_on(espocrm):
    user = espocrm.api.request("GET", "App/user")

    assert (user["user"]["userName"], user["user"]["type"]) == (API_USER, "api")
    assert espocrm.api.http.get("Role").status_code == 403
    assert user["settings"]["useWebSocket"] is True
    assert websocket_handshake(espocrm.websocket).startswith("HTTP/1.1 101")


def websocket_handshake(address: str) -> str:
    """Статусная строка ответа сервера WebSocket EspoCRM на запрос Upgrade (протокол WAMP)."""
    host, port = address.rsplit(":", 1)
    request = (
        "GET / HTTP/1.1\r\n"
        f"Host: {address}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Protocol: wamp\r\n\r\n"
    )
    with socket.create_connection((host, int(port)), timeout=5) as sock:
        sock.sendall(request.encode())
        # За заголовками сервер сразу шлёт двоичный кадр WAMP: читаем только статусную строку.
        return sock.recv(1024).split(b"\r\n")[0].decode()

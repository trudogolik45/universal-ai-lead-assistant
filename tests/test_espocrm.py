"""Контрактные тесты на втором шве: настоящая EspoCRM стенда.

Образ с модулем Uala (deploy/espocrm), Postgres стенда и API-пользователь n8n
(scripts/espocrm_bootstrap.py) — те же, что в проде. Фикстура `espocrm` — tests/conftest.py.
"""

import json
import socket
import uuid

from scripts.espocrm import EspoCrm
from scripts.espocrm_bootstrap import API_USER, ensure_api_user
from scripts.espocrm_knowledge import DEMO_CALENDAR, seed_calendar, seed_knowledge
from tests.booking import WORKING_CALENDAR_NODE, WORKING_RANGES_NODE, adapter_query, busy_where
from tests.espocrm import EMPLOYEE_REPLY_PATH, N8N_HOOK_SECRET, ESTIMATE_PATH, REPAIR_STATUS_PATH, TASK_DONE_PATH
from tests.knowledge import assistant_knowledge_query
from tests.marketing import consented_where, conversations_of_where
from tests.owner_report import report_where
from tests.polling import eventually, stays
from tests.reminders import planned_where


def create_conversation(espocrm, sender_id: str) -> dict:
    client = espocrm.api.create("Contact", {"firstName": "Jan", "lastName": "Kowalski"})
    return espocrm.api.create(
        "Conversation",
        {"name": "Jan Kowalski · Messenger", "channel": "messenger", "senderId": sender_id, "contactId": client["id"]},
    )


def test_api_user_creates_conversation_and_reads_it_back(espocrm):
    client = espocrm.api.create("Contact", {"firstName": "Jan", "lastName": "Kowalski"})

    created = espocrm.api.create(
        "Conversation",
        {"name": "Jan Kowalski · Messenger", "channel": "messenger", "senderId": "psid-100", "contactId": client["id"]},
    )

    conversation = espocrm.api.read("Conversation", created["id"])
    assert (conversation["channel"], conversation["senderId"], conversation["contactId"]) == (
        "messenger",
        "psid-100",
        client["id"],
    )


def test_api_user_adds_client_and_assistant_messages_to_conversation(espocrm):
    conversation = create_conversation(espocrm, "psid-200")

    espocrm.api.create(
        "Message",
        {
            "conversationId": conversation["id"],
            "direction": "in",
            "author": "client",
            "text": "Dzień dobry, ile kosztuje wymiana oleju?",
            "providerMessageId": "m_200",
        },
    )
    espocrm.api.create(
        "Message",
        {"conversationId": conversation["id"], "direction": "out", "author": "assistant", "text": "Wymiana oleju — 150 zł."},
    )

    messages = espocrm.api.related("Conversation", conversation["id"], "messages")
    assert sorted((m["direction"], m["author"], m["text"], m["providerMessageId"]) for m in messages) == [
        ("in", "client", "Dzień dobry, ile kosztuje wymiana oleju?", "m_200"),
        ("out", "assistant", "Wymiana oleju — 150 zł.", None),
    ]


def test_api_user_finds_conversation_by_channel_and_sender_as_crm_adapter_does(espocrm):
    wanted = create_conversation(espocrm, "psid-210")
    create_conversation(espocrm, "psid-211")

    found = espocrm.api.find(
        "Conversation",
        [
            {"type": "equals", "attribute": "channel", "value": "messenger"},
            {"type": "equals", "attribute": "senderId", "value": "psid-210"},
        ],
        select=["id"],
        maxSize=1,
    )

    assert [c["id"] for c in found] == [wanted["id"]]


def test_conversation_messages_are_ordered_by_sent_time_not_by_write_time(espocrm):
    conversation = create_conversation(espocrm, "psid-220")
    for text, sent_at in (("Odpowiedź", "2026-10-23 10:00:07"), ("Pytanie", "2026-10-23 10:00:01")):
        espocrm.api.create(
            "Message",
            {"conversationId": conversation["id"], "direction": "in", "author": "client", "text": text, "sentAt": sent_at},
        )

    messages = espocrm.api.related("Conversation", conversation["id"], "messages")

    assert [(m["text"], m["sentAt"]) for m in messages] == [
        ("Pytanie", "2026-10-23 10:00:01"),
        ("Odpowiedź", "2026-10-23 10:00:07"),
    ]


def test_message_author_is_client_assistant_or_employee(espocrm):
    conversation = create_conversation(espocrm, "psid-300")

    response = espocrm.api.http.post(
        "Message",
        json={"conversationId": conversation["id"], "direction": "in", "author": "bot", "text": "?"},
    )

    assert response.status_code == 400


def test_api_user_finds_client_vehicles(espocrm):
    client = espocrm.api.create("Contact", {"firstName": "Anna", "lastName": "Nowak"})

    espocrm.api.create(
        "Vehicle",
        {"name": "Toyota Corolla", "brand": "Toyota", "model": "Corolla", "year": 2015, "contactId": client["id"]},
    )

    vehicles = espocrm.api.related("Contact", client["id"], "vehicles")
    assert [(v["brand"], v["model"], v["year"]) for v in vehicles] == [("Toyota", "Corolla", 2015)]


def test_api_user_writes_lead_of_client_with_vehicle_in_conversation(espocrm):
    conversation = create_conversation(espocrm, "psid-400")
    client_id = conversation["contactId"]
    vehicle = espocrm.api.create(
        "Vehicle", {"name": "Skoda Octavia", "brand": "Skoda", "model": "Octavia", "contactId": client_id}
    )

    created = espocrm.api.create(
        "Lead",
        {
            "firstName": "Jan",
            "lastName": "Kowalski",
            "phoneNumber": "+48600123456",
            "description": "Stuki w zawieszeniu przy hamowaniu",
            "service": "Diagnostyka zawieszenia",
            "desiredTime": "jutro po 16:00",
            "contactId": client_id,
            "vehicleId": vehicle["id"],
            "conversationId": conversation["id"],
        },
    )
    espocrm.api.update("Lead", created["id"], {"desiredTime": "w piątek rano"})

    lead = espocrm.api.read("Lead", created["id"])
    assert (lead["service"], lead["desiredTime"], lead["phoneNumber"], lead["status"]) == (
        "Diagnostyka zawieszenia",
        "w piątek rano",
        "+48600123456",
        "New",
    )
    assert [r["id"] for r in espocrm.api.related("Contact", client_id, "leads")] == [created["id"]]
    assert [r["id"] for r in espocrm.api.related("Vehicle", vehicle["id"], "leads")] == [created["id"]]
    assert [r["id"] for r in espocrm.api.related("Conversation", conversation["id"], "leads")] == [created["id"]]


def test_crm_refuses_lead_and_client_without_last_name_or_with_phone_without_country_code(espocrm):
    """Поэтому переходник CRM подставляет имя Беседы вместо неизвестного имени
    и не пишет телефон не в международном формате."""
    headers = {"X-Skip-Duplicate-Check": "true"}

    refused = [
        espocrm.api.http.post(entity, json=data, headers=headers).status_code
        for entity, data in (
            ("Lead", {"description": "Stuki w zawieszeniu"}),
            ("Contact", {"firstName": "Jan"}),
            ("Lead", {"lastName": "Kowalski", "phoneNumber": "600123456"}),
        )
    ]
    accepted = espocrm.api.http.post("Lead", json={"lastName": "Kowalski", "phoneNumber": "+48600123456"}, headers=headers)

    assert refused == [400, 400, 400]
    assert accepted.status_code == 200


def test_client_has_no_marketing_consent_until_given(espocrm):
    client = espocrm.api.create("Contact", {"firstName": "Piotr", "lastName": "Zieliński"})
    assert espocrm.api.read("Contact", client["id"])["marketingConsent"] is False

    espocrm.api.update("Contact", client["id"], {"marketingConsent": True})

    assert espocrm.api.read("Contact", client["id"])["marketingConsent"] is True


def test_api_user_finds_conversations_of_consented_clients_as_crm_adapter_does(espocrm):
    agreed = espocrm.api.create("Contact", {"lastName": "Zgoda", "marketingConsent": True})
    refused = espocrm.api.create("Contact", {"lastName": "Brak"})
    for contact, sender_id in ((agreed, "48600333001"), (refused, "48600333002")):
        espocrm.api.create("Conversation", {
            "name": f"whatsapp · {sender_id}", "channel": "whatsapp", "senderId": sender_id, "contactId": contact["id"],
        })

    contacts = espocrm.api.find("Contact", consented_where(), select=["id"], maxSize=200)
    conversations = espocrm.api.find(
        "Conversation", conversations_of_where([c["id"] for c in contacts]), select=["channel", "senderId"], maxSize=200
    )

    assert agreed["id"] in {c["id"] for c in contacts} and refused["id"] not in {c["id"] for c in contacts}
    senders = {(c["channel"], c["senderId"]) for c in conversations}
    assert ("whatsapp", "48600333001") in senders and ("whatsapp", "48600333002") not in senders


def test_n8n_works_as_api_user_without_admin_rights(espocrm):
    user = espocrm.api.request("GET", "App/user")["user"]

    assert (user["userName"], user["type"]) == (API_USER, "api")
    assert espocrm.api.http.get("Role").status_code == 403


def test_bootstrap_again_keeps_the_same_api_user_and_key(espocrm):
    key = ensure_api_user(espocrm.admin)

    users = espocrm.admin.find("User", [{"type": "equals", "attribute": "userName", "value": API_USER}])
    assert len(users) == 1
    assert key == espocrm.api.http.headers["X-Api-Key"]


def test_websocket_is_enabled_and_accepts_connections(espocrm):
    settings = espocrm.api.request("GET", "App/user")["settings"]

    assert settings["useWebSocket"] is True
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


EMPLOYEE_PASSWORD = "test-employee-1"


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


def find_ids(client, entity: str, where: list[dict], **params) -> list[str]:
    return [record["id"] for record in client.find(entity, where, select=["id"], **params)]


def test_api_user_finds_active_team_members_as_crm_adapter_does(espocrm):
    team_id = find_ids(espocrm.api, "Team", [{"type": "equals", "attribute": "name", "value": "Administratorzy"}])[0]
    member = employee(espocrm, "Administratorzy")
    inactive = employee(espocrm, "Administratorzy")
    espocrm.admin.update("User", inactive["id"], {"isActive": False})
    mechanic = employee(espocrm, "Mechanicy")

    members = find_ids(
        espocrm.api,
        "User",
        [
            {"type": "linkedWith", "attribute": "teams", "value": [team_id]},
            {"type": "equals", "attribute": "isActive", "value": True},
        ],
        orderBy="userName",
        order="asc",
        maxSize=200,
    )

    assert member["id"] in members
    assert {inactive["id"], mechanic["id"]}.isdisjoint(members)


def test_api_user_counts_open_tasks_of_employee_as_crm_adapter_does(espocrm):
    user = employee(espocrm, "Administratorzy", open_tasks=2)
    espocrm.admin.create("Task", {"name": "Zrobione", "status": "Completed", "assignedUserId": user["id"]})

    found = espocrm.api.request(
        "GET",
        "Task",
        params={
            "searchParams": json.dumps(
                {
                    "where": [
                        {"type": "equals", "attribute": "assignedUserId", "value": user["id"]},
                        {"type": "in", "attribute": "status", "value": ["Not Started", "Started"]},
                    ],
                    "select": ["id"],
                    "maxSize": 1,
                }
            )
        },
    )

    assert found["total"] == 2


def test_handoff_task_links_to_conversation_and_notifies_assigned_employee(espocrm):
    conversation = create_conversation(espocrm, "psid-240")
    user = employee(espocrm, "Administratorzy")
    team_id = user["teamsIds"][0]

    task = espocrm.api.create(
        "Task",
        {
            "name": "Przekazanie rozmowy: Jan Kowalski",
            "description": "Powód: klient prosi o człowieka",
            "status": "Not Started",
            "parentType": "Conversation",
            "parentId": conversation["id"],
            "assignedUserId": user["id"],
            "teamsIds": [team_id],
        },
    )

    assert [t["id"] for t in espocrm.api.related("Conversation", conversation["id"], "tasks")] == [task["id"]]
    as_employee = EspoCrm(espocrm.url, admin=(user["userName"], EMPLOYEE_PASSWORD))
    assert eventually(lambda: task["id"] in notified_records(as_employee))


def notified_records(client) -> list[str]:
    """id записей, о которых сотруднику пришли уведомления CRM."""
    notifications = client.request("GET", "Notification", params={"maxSize": 50})["list"]
    return [n["relatedParentId"] for n in notifications]


def test_crm_emails_employee_about_assigned_task(espocrm):
    """Письмо уходит job-ом SendEmailNotifications через SMTP CRM; тут — что Task в списке рассылки."""
    settings = espocrm.admin.request("GET", "Settings")

    assert "Task" in settings["assignmentEmailNotificationsEntityList"]


def create_knowledge_item(espocrm, **fields) -> dict:
    return espocrm.admin.create("KnowledgeItem", fields)


def knowledge_base(client) -> list[dict]:
    """База знаний тем же запросом, что шлёт Ассистент (узел «Load knowledge base» в n8n)."""
    return client.request("GET", "KnowledgeItem", params=assistant_knowledge_query())["list"]


def test_api_user_reads_knowledge_base_as_assistant_does(espocrm):
    item = create_knowledge_item(
        espocrm,
        name="Wymiana klocków hamulcowych (kontrakt)",
        kind="service",
        description="Jedna oś, bez kosztu klocków. Około 1 godziny.",
        price=140,
        priceFrom=True,
    )

    read = next(found for found in knowledge_base(espocrm.api) if found["id"] == item["id"])

    assert (read["name"], read["kind"], read["description"], read["price"], read["priceFrom"]) == (
        "Wymiana klocków hamulcowych (kontrakt)",
        "service",
        "Jedna oś, bez kosztu klocków. Około 1 godziny.",
        140,
        True,
    )


def test_owner_edit_in_crm_is_read_by_api_user_right_away(espocrm):
    item = create_knowledge_item(espocrm, name="Diagnostyka zawieszenia (kontrakt)", kind="service", price=100)

    espocrm.admin.update("KnowledgeItem", item["id"], {"price": 110})

    assert [found["price"] for found in knowledge_base(espocrm.api) if found["id"] == item["id"]] == [110]


def test_knowledge_kind_is_service_hours_company_faq_or_rule(espocrm):
    response = espocrm.admin.http.post("KnowledgeItem", json={"name": "Promocja", "kind": "promo"})

    assert response.status_code == 400


def test_api_user_cannot_change_knowledge_base(espocrm):
    response = espocrm.api.http.post("KnowledgeItem", json={"name": "Wymiana oleju za 1 zł", "kind": "service"})

    assert response.status_code == 403


def knowledge_total(espocrm) -> int:
    return espocrm.admin.request("GET", "KnowledgeItem", params={"maxSize": 1})["total"]


def test_demo_knowledge_base_is_seeded_once_and_keeps_owner_edits(espocrm):
    seed_knowledge(espocrm.admin)
    total = knowledge_total(espocrm)
    oil = espocrm.admin.find(
        "KnowledgeItem", [{"type": "equals", "attribute": "name", "value": "Wymiana oleju silnikowego i filtra oleju"}]
    )[0]
    espocrm.admin.update("KnowledgeItem", oil["id"], {"price": 130})

    seed_knowledge(espocrm.admin)

    assert knowledge_total(espocrm) == total
    assert espocrm.admin.read("KnowledgeItem", oil["id"])["price"] == 130
    assert {item["kind"] for item in knowledge_base(espocrm.admin)} == {"service", "hours", "company", "faq", "rule"}


def test_api_user_reads_working_time_calendar_as_crm_adapter_does(espocrm):
    """Рабочий календарь — встроенный WorkingTimeCalendar с исключениями (праздники): график правит Заказчик."""
    created = espocrm.admin.create(
        "WorkingTimeCalendar",
        {
            "name": "Aaa kontrakt",
            "timeZone": "Europe/Warsaw",
            "timeRanges": [["8:00", "18:00"]],
            "weekday6": True,
            "weekday6TimeRanges": [["9:00", "14:00"]],
        },
    )
    espocrm.admin.create(
        "WorkingTimeRange",
        {"type": "Non-working", "dateStart": "2031-12-24", "dateEnd": "2031-12-26", "calendarsIds": [created["id"]]},
    )

    found = espocrm.api.request("GET", "WorkingTimeCalendar", params=adapter_query(WORKING_CALENDAR_NODE))
    ranges = espocrm.api.request(
        "GET", f"WorkingTimeCalendar/{created['id']}/ranges", params=adapter_query(WORKING_RANGES_NODE)
    )["list"]
    espocrm.admin.request("DELETE", f"WorkingTimeCalendar/{created['id']}")

    [calendar] = found["list"]
    assert (calendar["id"], calendar["timeZone"], calendar["timeRanges"]) == (
        created["id"], "Europe/Warsaw", [["8:00", "18:00"]]
    )
    assert [calendar[f"weekday{day}"] for day in range(7)] == [False, True, True, True, True, True, True]
    assert calendar["weekday6TimeRanges"] == [["9:00", "14:00"]]
    assert [(r["type"], r["dateStart"], r["dateEnd"]) for r in ranges] == [("Non-working", "2031-12-24", "2031-12-26")]


def overlapping_meetings(client, starts_at: str, ends_at: str) -> list[str]:
    """Записи, которые пересекаются со слотом, — тем же условием, что у переходника CRM."""
    return find_ids(client, "Meeting", busy_where(starts_at, ends_at), maxSize=200)


def test_api_user_finds_meetings_overlapping_slot(espocrm):
    booked = espocrm.api.create(
        "Meeting", {"name": "Wizyta", "dateStart": "2031-03-03 09:00:00", "dateEnd": "2031-03-03 10:00:00"}
    )
    espocrm.api.create(
        "Meeting",
        {"name": "Odwołana", "dateStart": "2031-03-03 10:00:00", "dateEnd": "2031-03-03 11:00:00", "status": "Not Held"},
    )

    assert overlapping_meetings(espocrm.api, "2031-03-03 09:30:00", "2031-03-03 10:30:00") == [booked["id"]]
    assert overlapping_meetings(espocrm.api, "2031-03-03 10:00:00", "2031-03-03 11:00:00") == []
    assert overlapping_meetings(espocrm.api, "2031-03-03 08:00:00", "2031-03-03 09:00:00") == []


def test_api_user_finds_planned_meetings_to_remind(espocrm):
    planned = espocrm.api.create(
        "Meeting", {"name": "Wizyta", "dateStart": "2031-04-01 09:00:00", "dateEnd": "2031-04-01 10:00:00"}
    )
    espocrm.api.create(
        "Meeting",
        {"name": "Odwołana", "dateStart": "2031-04-01 11:00:00", "dateEnd": "2031-04-01 12:00:00", "status": "Not Held"},
    )
    espocrm.api.create(
        "Meeting", {"name": "Później", "dateStart": "2031-04-02 09:00:00", "dateEnd": "2031-04-02 10:00:00"}
    )

    found = find_ids(espocrm.api, "Meeting", planned_where("2031-04-01 08:00:00", "2031-04-02 08:00:00"), maxSize=200)

    assert found == [planned["id"]]


def test_api_user_books_meeting_for_client_and_vehicle_without_assignee(espocrm):
    client = espocrm.api.create("Contact", {"firstName": "Jan", "lastName": "Kowalski"})
    vehicle = espocrm.api.create("Vehicle", {"name": "Skoda Octavia", "contactId": client["id"]})

    meeting = espocrm.api.create(
        "Meeting",
        {"name": "Wizyta: Jan Kowalski", "dateStart": "2031-03-04 09:00:00", "dateEnd": "2031-03-04 10:00:00"},
    )
    espocrm.api.update("Meeting", meeting["id"], {"contactsIds": [client["id"]], "vehicleId": vehicle["id"]})

    read = espocrm.api.read("Meeting", meeting["id"])
    assert (read["status"], read["dateStart"], read["dateEnd"], read["assignedUserId"]) == (
        "Planned", "2031-03-04 09:00:00", "2031-03-04 10:00:00", None
    )
    assert [m["id"] for m in espocrm.api.related("Contact", client["id"], "meetings")] == [meeting["id"]]
    assert [m["id"] for m in espocrm.api.related("Vehicle", vehicle["id"], "meetings")] == [meeting["id"]]


def channel_total(client, entity: str, starts_at: str, ends_at: str, channel: str) -> int:
    """Сколько записей Канала создано в периоде — тем же запросом, что у переходника CRM (только total)."""
    search = json.dumps({"where": report_where(starts_at, ends_at, channel), "select": ["id"], "maxSize": 1})
    return client.request("GET", entity, params={"searchParams": search})["total"]


def test_api_user_counts_leads_and_meetings_of_channel_created_in_period(espocrm):
    period = ("2000-01-01 00:00:00", "2100-01-01 00:00:00")
    before = {entity: channel_total(espocrm.api, entity, *period, "call") for entity in ("Lead", "Meeting")}

    lead = espocrm.api.create("Lead", {"lastName": "Nowak", "channel": "call"})
    espocrm.api.create("Lead", {"lastName": "Nowak", "channel": "whatsapp"})
    meeting = espocrm.api.create(
        "Meeting", {"name": "Wizyta", "dateStart": "2031-03-05 09:00:00", "dateEnd": "2031-03-05 10:00:00"}
    )
    espocrm.api.update("Meeting", meeting["id"], {"channel": "call"})

    assert channel_total(espocrm.api, "Lead", *period, "call") == before["Lead"] + 1
    assert channel_total(espocrm.api, "Meeting", *period, "call") == before["Meeting"] + 1
    created_at = espocrm.api.read("Lead", lead["id"])["createdAt"]
    assert channel_total(espocrm.api, "Lead", created_at, created_at, "call") == 0
    assert channel_total(espocrm.api, "Lead", "2000-01-01 00:00:00", created_at, "call") == before["Lead"]


def autopro_calendar(espocrm) -> list[dict]:
    return espocrm.admin.find("WorkingTimeCalendar", [{"type": "equals", "attribute": "name", "value": DEMO_CALENDAR}])


def test_demo_working_calendar_is_seeded_once_and_keeps_owner_edits(espocrm):
    seed_calendar(espocrm.admin)
    [calendar] = autopro_calendar(espocrm)
    espocrm.admin.update("WorkingTimeCalendar", calendar["id"], {"weekday6": False})

    seed_calendar(espocrm.admin)

    [read] = autopro_calendar(espocrm)
    assert (read["timeZone"], read["timeRanges"], read["weekday0"], read["weekday1"], read["weekday6"]) == (
        "Europe/Warsaw", [["8:00", "18:00"]], False, True, False
    )
    assert read["weekday6TimeRanges"] == [["9:00", "14:00"]]


def employee_replies(fake) -> list:
    return fake.requests(EMPLOYEE_REPLY_PATH)


def test_employee_message_in_conversation_calls_n8n_with_text_and_client_address(espocrm, fake):
    conversation = create_conversation(espocrm, "psid-400")
    user = employee(espocrm, "Administratorzy")
    as_employee = EspoCrm(espocrm.url, admin=(user["userName"], EMPLOYEE_PASSWORD))

    # Сотрудник пишет из Беседы: направление и автора не выбирает.
    message = as_employee.create("Message", {"conversationId": conversation["id"], "text": "Auto gotowe do odbioru."})

    [call] = eventually(lambda: employee_replies(fake))
    assert call.method == "POST"
    assert call.headers["X-Uala-Secret"] == N8N_HOOK_SECRET
    assert call.json() == {
        "crm_message_id": message["id"],
        "channel": "messenger",
        "sender_id": "psid-400",
        "text": "Auto gotowe do odbioru.",
    }
    saved = espocrm.admin.read("Message", message["id"])
    assert (saved["direction"], saved["author"], bool(saved["sentAt"])) == ("out", "employee", True)


def test_messages_written_by_n8n_do_not_call_n8n_back(espocrm, fake):
    conversation = create_conversation(espocrm, "psid-410")

    espocrm.api.create(
        "Message",
        {"conversationId": conversation["id"], "direction": "out", "author": "assistant", "text": "Wymiana oleju — 150 zł."},
    )

    stays(lambda: employee_replies(fake) == [])


def handoff_task(espocrm, user: dict, conversation: dict) -> dict:
    return espocrm.api.create(
        "Task",
        {
            "name": "Przekazanie rozmowy: Jan Kowalski",
            "status": "Not Started",
            "parentType": "Conversation",
            "parentId": conversation["id"],
            "assignedUserId": user["id"],
            "teamsIds": user["teamsIds"],
        },
    )


def done_tasks(fake) -> list:
    return fake.requests(TASK_DONE_PATH)


def test_employee_closing_conversation_task_calls_n8n_with_task_id(espocrm, fake):
    user = employee(espocrm, "Administratorzy")
    task = handoff_task(espocrm, user, create_conversation(espocrm, "psid-420"))
    as_employee = EspoCrm(espocrm.url, admin=(user["userName"], EMPLOYEE_PASSWORD))

    as_employee.update("Task", task["id"], {"status": "Completed"})

    [call] = eventually(lambda: done_tasks(fake))
    assert call.headers["X-Uala-Secret"] == N8N_HOOK_SECRET
    assert call.json() == {"crm_task_id": task["id"]}


def test_task_still_open_or_without_conversation_does_not_call_n8n(espocrm, fake):
    user = employee(espocrm, "Administratorzy")
    task = handoff_task(espocrm, user, create_conversation(espocrm, "psid-430"))
    other = espocrm.admin.create("Task", {"name": "Zamówić części", "status": "Not Started", "assignedUserId": user["id"]})

    espocrm.admin.update("Task", task["id"], {"status": "Started"})
    espocrm.admin.update("Task", other["id"], {"status": "Completed"})

    stays(lambda: done_tasks(fake) == [])


def repair_order(espocrm, status: str = "New") -> tuple[dict, list[dict]]:
    """Заказ-наряд Клиента, который писал в Messenger и WhatsApp; возвращает его и Беседы Клиента."""
    client = espocrm.api.create("Contact", {"firstName": "Jan", "lastName": "Kowalski"})
    conversations = [
        {"channel": channel, "sender_id": f"{channel}-{uuid.uuid4().hex[:8]}"} for channel in ("messenger", "whatsapp")
    ]
    for c in conversations:
        espocrm.api.create(
            "Conversation",
            {"name": f"Jan Kowalski · {c['channel']}", "channel": c["channel"], "senderId": c["sender_id"],
             "contactId": client["id"]},
        )
    vehicle = espocrm.api.create("Vehicle", {"name": "Skoda Octavia", "contactId": client["id"]})
    order = espocrm.admin.create(
        "RepairOrder",
        {"name": "Skoda Octavia: wymiana sprzęgła", "status": status, "contactId": client["id"],
         "vehicleId": vehicle["id"]},
    )
    return order, conversations


def repair_statuses(fake) -> list:
    return fake.requests(REPAIR_STATUS_PATH)


def test_repair_order_belongs_to_client_vehicle_and_appointment(espocrm):
    client = espocrm.api.create("Contact", {"firstName": "Anna", "lastName": "Nowak"})
    vehicle = espocrm.api.create("Vehicle", {"name": "Toyota Corolla", "contactId": client["id"]})
    meeting = espocrm.api.create(
        "Meeting", {"name": "Wizyta: Anna Nowak", "dateStart": "2031-05-06 09:00:00", "dateEnd": "2031-05-06 10:00:00"}
    )
    user = employee(espocrm, "Mechanicy")
    as_mechanic = EspoCrm(espocrm.url, admin=(user["userName"], EMPLOYEE_PASSWORD))

    order = as_mechanic.create(
        "RepairOrder",
        {"name": "Toyota Corolla: hamulce", "contactId": client["id"], "vehicleId": vehicle["id"],
         "meetingId": meeting["id"]},
    )

    read = espocrm.api.read("RepairOrder", order["id"])
    assert (read["status"], read["contactId"], read["vehicleId"], read["meetingId"]) == (
        "New", client["id"], vehicle["id"], meeting["id"]
    )
    for entity, record in (("Contact", client), ("Vehicle", vehicle), ("Meeting", meeting)):
        assert [o["id"] for o in espocrm.api.related(entity, record["id"], "repairOrders")] == [order["id"]]


def test_repair_order_status_is_one_of_the_workshop_statuses(espocrm):
    response = espocrm.admin.http.post("RepairOrder", json={"name": "Auto", "status": "Lost"})

    assert response.status_code == 400


def test_mechanic_changing_repair_status_calls_n8n_with_status_and_client_conversations(espocrm, fake):
    order, conversations = repair_order(espocrm)
    user = employee(espocrm, "Mechanicy")
    as_mechanic = EspoCrm(espocrm.url, admin=(user["userName"], EMPLOYEE_PASSWORD))

    as_mechanic.update("RepairOrder", order["id"], {"status": "Waiting for Parts"})

    [call] = eventually(lambda: [
        r for r in repair_statuses(fake)
        if r.json()["crm_repair_order_id"] == order["id"] and r.json()["status"] == "Waiting for Parts"
    ])
    assert call.headers["X-Uala-Secret"] == N8N_HOOK_SECRET
    body = call.json()
    assert body["name"] == "Skoda Octavia: wymiana sprzęgła"
    assert sorted(body["conversations"], key=lambda c: c["channel"]) == conversations


def test_repair_order_saved_without_status_change_does_not_call_n8n(espocrm, fake):
    order, _ = repair_order(espocrm)
    eventually(lambda: [r for r in repair_statuses(fake) if r.json()["crm_repair_order_id"] == order["id"]])
    fake.reset()

    espocrm.admin.update("RepairOrder", order["id"], {"description": "Klient prosi o telefon przed wymianą."})

    stays(lambda: repair_statuses(fake) == [])


def test_estimate_task_links_to_repair_order_and_notifies_assigned_mechanic(espocrm):
    order, _ = repair_order(espocrm)
    user = employee(espocrm, "Mechanicy")

    task = espocrm.api.create(
        "Task",
        {"name": "Kosztorys: Skoda Octavia: wymiana sprzęgła", "status": "Not Started",
         "parentType": "RepairOrder", "parentId": order["id"],
         "assignedUserId": user["id"], "teamsIds": user["teamsIds"]},
    )

    assert [t["id"] for t in espocrm.api.related("RepairOrder", order["id"], "tasks")] == [task["id"]]
    as_mechanic = EspoCrm(espocrm.url, admin=(user["userName"], EMPLOYEE_PASSWORD))
    assert eventually(lambda: task["id"] in notified_records(as_mechanic))


def estimate_calls(fake, estimate_id: str) -> list:
    return [r for r in fake.requests(ESTIMATE_PATH) if r.json()["crm_estimate_id"] == estimate_id]


def test_mechanic_writes_estimate_of_repair_order_with_amount(espocrm):
    order, _ = repair_order(espocrm)
    user = employee(espocrm, "Mechanicy")
    as_mechanic = EspoCrm(espocrm.url, admin=(user["userName"], EMPLOYEE_PASSWORD))

    estimate = as_mechanic.create(
        "Estimate",
        {"name": "Wymiana sprzęgła", "repairOrderId": order["id"], "amount": 1250.5, "amountCurrency": "PLN",
         "description": "Sprzęgło LUK, robocizna 4 h"},
    )

    read = espocrm.api.read("Estimate", estimate["id"])
    assert (read["status"], read["amount"], read["amountCurrency"]) == ("Draft", 1250.5, "PLN")
    assert [e["id"] for e in espocrm.api.related("RepairOrder", order["id"], "estimates")] == [estimate["id"]]


def test_estimate_needs_repair_order_and_known_status(espocrm):
    order, _ = repair_order(espocrm)
    without_order = {"name": "Kosztorys", "amount": 100, "amountCurrency": "PLN"}

    assert espocrm.api.http.post("Estimate", json=without_order).status_code == 400
    assert espocrm.api.http.post(
        "Estimate", json={**without_order, "repairOrderId": order["id"], "status": "Sent"}
    ).status_code == 400


def test_estimate_ready_calls_n8n_with_amount_and_client_conversations(espocrm, fake):
    order, conversations = repair_order(espocrm)
    estimate = espocrm.admin.create(
        "Estimate", {"name": "Wymiana sprzęgła", "repairOrderId": order["id"], "amount": 1250.5, "amountCurrency": "PLN"}
    )
    user = employee(espocrm, "Mechanicy")
    as_mechanic = EspoCrm(espocrm.url, admin=(user["userName"], EMPLOYEE_PASSWORD))

    as_mechanic.update("Estimate", estimate["id"], {"status": "Ready"})

    [call] = eventually(lambda: [r for r in estimate_calls(fake, estimate["id"]) if r.json()["status"] == "Ready"])
    assert call.headers["X-Uala-Secret"] == N8N_HOOK_SECRET
    body = call.json()
    assert (body["crm_repair_order_id"], body["name"], body["amount"], body["currency"]) == (
        order["id"], "Wymiana sprzęgła", 1250.5, "PLN"
    )
    assert sorted(body["conversations"], key=lambda c: c["channel"]) == conversations


def test_estimate_saved_without_status_change_does_not_call_n8n(espocrm, fake):
    order, _ = repair_order(espocrm)
    estimate = espocrm.admin.create(
        "Estimate", {"name": "Hamulce", "repairOrderId": order["id"], "amount": 400, "amountCurrency": "PLN"}
    )
    eventually(lambda: estimate_calls(fake, estimate["id"]))
    fake.reset()

    espocrm.admin.update("Estimate", estimate["id"], {"description": "Klocki i tarcze"})

    stays(lambda: estimate_calls(fake, estimate["id"]) == [])

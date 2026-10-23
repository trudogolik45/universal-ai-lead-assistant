"""Контрактные тесты на втором шве: настоящая EspoCRM стенда.

Образ с модулем Uala (deploy/espocrm), Postgres стенда и API-пользователь n8n
(scripts/espocrm_bootstrap.py) — те же, что в проде. Фикстура `espocrm` — tests/conftest.py.
"""

import socket

from scripts.espocrm_bootstrap import API_USER, ensure_api_user
from scripts.espocrm_knowledge import seed_knowledge
from tests.espocrm import EMPLOYEE_REPLY_PATH, EMPLOYEE_REPLY_SECRET
from tests.knowledge import assistant_knowledge_query
from tests.polling import eventually, stays


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


def test_client_has_no_marketing_consent_until_given(espocrm):
    client = espocrm.api.create("Contact", {"firstName": "Piotr", "lastName": "Zieliński"})
    assert espocrm.api.read("Contact", client["id"])["marketingConsent"] is False

    espocrm.api.update("Contact", client["id"], {"marketingConsent": True})

    assert espocrm.api.read("Contact", client["id"])["marketingConsent"] is True


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


def employee_replies(fake) -> list:
    return fake.requests(EMPLOYEE_REPLY_PATH)


def test_employee_message_in_conversation_calls_n8n_with_text_and_client_address(espocrm, fake):
    conversation = create_conversation(espocrm, "psid-400")

    # Сотрудник пишет из Беседы: направление и автора не выбирает.
    message = espocrm.admin.create("Message", {"conversationId": conversation["id"], "text": "Auto gotowe do odbioru."})

    [call] = eventually(lambda: employee_replies(fake))
    assert call.method == "POST"
    assert call.headers["X-Uala-Secret"] == EMPLOYEE_REPLY_SECRET
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

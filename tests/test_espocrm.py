"""Контрактные тесты на втором шве: настоящая EspoCRM стенда.

Образ с модулем Uala (deploy/espocrm), Postgres стенда и API-пользователь n8n
(scripts/espocrm_bootstrap.py) — те же, что в проде. Фикстура `espocrm` — tests/conftest.py.
"""

import socket

from scripts.espocrm_bootstrap import API_USER, ensure_api_user


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

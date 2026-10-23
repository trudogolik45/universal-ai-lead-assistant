"""Фейк REST API EspoCRM: записи живут в памяти фейк-сервера, как в настоящей CRM.

Фейк отвечает так же, как настоящая EspoCRM на те же запросы (контракт — tests/test_espocrm.py):
тесты на главном шве читают, что n8n записал в CRM, а не перечисляют каждый HTTP-запрос.
"""

import json

import httpx
import pytest

from tests.fake_espocrm import API_KEY, FakeEspoCrm
from tests.fake_server import FakeServer, Response


@pytest.fixture
def server():
    server = FakeServer().start()
    yield server
    server.stop()


@pytest.fixture
def crm(server):
    crm = FakeEspoCrm()
    server.mount(FakeEspoCrm.PREFIX, crm)
    return crm


@pytest.fixture
def api(server, crm):
    with httpx.Client(base_url=f"http://127.0.0.1:{server.port}/espocrm/api/v1", headers={"X-Api-Key": API_KEY}) as client:
        yield client


def conversation(channel, sender_id):
    return {"name": f"{channel} · {sender_id}", "channel": channel, "senderId": sender_id}


def message(conversation_id, text, sent_at):
    return {"conversationId": conversation_id, "direction": "in", "author": "client", "text": text, "sentAt": sent_at}


def search(api, entity, where, **params):
    return api.get(entity, params={"searchParams": json.dumps({"where": where, **params})})


def test_created_record_gets_id_and_reads_back(api):
    created = api.post("Conversation", json=conversation("messenger", "psid-1")).json()

    assert created["id"]
    assert api.get(f"Conversation/{created['id']}").json() == created


def test_search_filters_by_equal_attributes(api):
    api.post("Conversation", json=conversation("messenger", "psid-1"))
    wanted = api.post("Conversation", json=conversation("instagram", "psid-1")).json()

    found = search(
        api,
        "Conversation",
        [
            {"type": "equals", "attribute": "channel", "value": "instagram"},
            {"type": "equals", "attribute": "senderId", "value": "psid-1"},
        ],
    ).json()

    assert found == {"total": 1, "list": [wanted]}


def test_search_understands_where_in_query_brackets(api):
    wanted = api.post("Conversation", json=conversation("messenger", "psid-2")).json()

    found = api.get(
        "Conversation",
        params={"where[0][type]": "equals", "where[0][attribute]": "senderId", "where[0][value]": "psid-2"},
    ).json()

    assert found["list"] == [wanted]


def test_related_messages_of_conversation_are_ordered(api):
    created = api.post("Conversation", json=conversation("messenger", "psid-3")).json()
    for text, sent_at in (("druga", "2026-10-23 10:00:05"), ("pierwsza", "2026-10-23 10:00:01")):
        api.post("Message", json=message(created["id"], text, sent_at))

    related = api.get(f"Conversation/{created['id']}/messages", params={"orderBy": "sentAt"}).json()

    assert [m["text"] for m in related["list"]] == ["pierwsza", "druga"]


def test_update_changes_only_given_fields(api):
    created = api.post("Conversation", json=conversation("messenger", "psid-4")).json()

    api.put(f"Conversation/{created['id']}", json={"senderId": "psid-5"})

    assert api.get(f"Conversation/{created['id']}").json() == {**created, "senderId": "psid-5"}


def test_record_without_required_fields_is_rejected(api, crm):
    response = api.post("Conversation", json={"channel": "messenger"})

    assert response.status_code == 400
    assert crm.records("Conversation") == []


def test_unknown_record_is_not_found(api):
    assert api.get("Conversation/missing").status_code == 404


def test_request_without_api_key_is_unauthorized(api):
    assert api.get("Conversation", headers={"X-Api-Key": "wrong"}).status_code == 401


def test_unavailable_crm_answers_503_and_keeps_no_records(api, crm):
    with crm.unavailable():
        response = api.post("Conversation", json=conversation("messenger", "psid-6"))

    assert response.status_code == 503
    assert crm.records("Conversation") == []


def test_crm_unavailable_for_one_entity_answers_others(api, crm):
    with crm.unavailable("Lead"):
        lead = api.post("Lead", json={"lastName": "Kowalski"})
        contact = api.post("Contact", json={"lastName": "Kowalski"})

    assert (lead.status_code, contact.status_code) == (503, 200)
    assert crm.records("Lead") == []


def test_phone_without_country_code_is_rejected_like_real_crm(api, crm):
    local = api.post("Lead", json={"lastName": "Kowalski", "phoneNumber": "600123456"})
    international = api.post("Lead", json={"lastName": "Kowalski", "phoneNumber": "+48600123456"})

    assert (local.status_code, international.status_code) == (400, 200)


def test_explicit_route_overrides_mounted_fake(server, api):
    server.respond("GET", "/espocrm/api/v1/KnowledgeItem", Response(500))

    assert api.get("KnowledgeItem").status_code == 500


def test_reset_of_server_forgets_records(server, api, crm):
    api.post("Conversation", json=conversation("messenger", "psid-7"))

    server.reset()

    assert crm.records("Conversation") == []

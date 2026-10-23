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


def search(api, entity, where, **params):
    return api.get(entity, params={"searchParams": json.dumps({"where": where, **params})})


def test_created_record_gets_id_and_reads_back(api):
    created = api.post("Conversation", json={"channel": "messenger", "senderId": "psid-1"}).json()

    assert created["id"]
    assert api.get(f"Conversation/{created['id']}").json() == created


def test_search_filters_by_equal_attributes(api):
    api.post("Conversation", json={"channel": "messenger", "senderId": "psid-1"})
    wanted = api.post("Conversation", json={"channel": "instagram", "senderId": "psid-1"}).json()

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
    wanted = api.post("Conversation", json={"channel": "messenger", "senderId": "psid-2"}).json()

    found = api.get(
        "Conversation",
        params={"where[0][type]": "equals", "where[0][attribute]": "senderId", "where[0][value]": "psid-2"},
    ).json()

    assert found["list"] == [wanted]


def test_related_messages_of_conversation_are_ordered(api):
    conversation = api.post("Conversation", json={"channel": "messenger", "senderId": "psid-3"}).json()
    api.post("Message", json={"conversationId": conversation["id"], "text": "druga", "sentAt": "2026-10-23 10:00:05"})
    api.post("Message", json={"conversationId": conversation["id"], "text": "pierwsza", "sentAt": "2026-10-23 10:00:01"})

    related = api.get(f"Conversation/{conversation['id']}/messages", params={"orderBy": "sentAt"}).json()

    assert [m["text"] for m in related["list"]] == ["pierwsza", "druga"]


def test_update_changes_only_given_fields(api):
    created = api.post("Conversation", json={"channel": "messenger", "senderId": "psid-4"}).json()

    api.put(f"Conversation/{created['id']}", json={"senderId": "psid-5"})

    assert api.get(f"Conversation/{created['id']}").json() == {**created, "senderId": "psid-5"}


def test_unknown_record_is_not_found(api):
    assert api.get("Conversation/missing").status_code == 404


def test_request_without_api_key_is_unauthorized(api):
    assert api.get("Conversation", headers={"X-Api-Key": "wrong"}).status_code == 401


def test_unavailable_crm_answers_503_and_keeps_no_records(api, crm):
    with crm.unavailable():
        response = api.post("Conversation", json={"channel": "messenger", "senderId": "psid-6"})

    assert response.status_code == 503
    assert crm.records("Conversation") == []


def test_explicit_route_overrides_mounted_fake(server, api):
    server.respond("GET", "/espocrm/api/v1/KnowledgeItem", Response(500))

    assert api.get("KnowledgeItem").status_code == 500


def test_reset_of_server_forgets_records(server, api, crm):
    api.post("Conversation", json={"channel": "messenger", "senderId": "psid-7"})

    server.reset()

    assert crm.records("Conversation") == []

"""Фейк REST API EspoCRM в фейк-сервере: записи в памяти, CRUD, обязательные поля, поиск по `equals`, связи.

Подключён к фейк-серверу фикстурой `fake_server` (префикс /espocrm, env n8n ESPOCRM_BASE_URL).
Тест читает записанное через `records(entity)` / `related(...)`, недоступность CRM — `unavailable()`.
Ответы повторяют настоящую EspoCRM на те же запросы (контракт — tests/test_espocrm.py);
новый вид связи — строка в LINKS.
"""

import json
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from tests.fake_server import Request, Response

# Значение из docker-compose.test.yml (ESPOCRM_API_KEY n8n стенда).
API_KEY = "test-espocrm-key"

# Обязательные поля (entityDefs модуля Uala): без них настоящая EspoCRM отвечает 400.
REQUIRED = {
    "Conversation": ("name", "channel", "senderId"),
    "Message": ("conversationId", "direction", "author", "text"),
    "Vehicle": ("name",),
}

# Связь hasMany (сущность, связь) → (связанная сущность, поле со ссылкой на родителя).
LINKS = {
    ("Conversation", "messages"): ("Message", "conversationId"),
    ("Contact", "conversations"): ("Conversation", "contactId"),
    ("Contact", "vehicles"): ("Vehicle", "contactId"),
}


class FakeEspoCrm:
    PREFIX = "/espocrm/api/v1/"

    def __init__(self, api_key: str = API_KEY):
        self._api_key = api_key
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, dict]] = {}
        self._available = True

    def reset(self):
        with self._lock:
            self._records.clear()
            self._available = True

    @contextmanager
    def unavailable(self):
        """CRM лежит: на любой запрос 503, пока блок не закончится."""
        self._available = False
        try:
            yield
        finally:
            self._available = True

    def records(self, entity: str) -> list[dict]:
        """Записи сущности в порядке создания."""
        with self._lock:
            return [dict(r) for r in self._records.get(entity, {}).values()]

    def related(self, entity: str, record_id: str, link: str, order_by: str | None = None) -> list[dict]:
        with self._lock:
            return self._related(entity, record_id, link, order_by)

    def __call__(self, request: Request) -> Response:
        if not self._available:
            return Response(503, None)
        if header(request, "X-Api-Key") != self._api_key:
            return Response(401, None)
        url = urlsplit(request.path)
        parts = url.path.removeprefix(self.PREFIX).split("/")
        params = {key: values[-1] for key, values in parse_qs(url.query).items()}
        with self._lock:
            return self._route(request.method, parts, params, request.body)

    def _route(self, method: str, parts: list[str], params: dict, body: bytes) -> Response:
        match method, parts:
            case "POST", [entity]:
                return self._create(entity, json.loads(body or b"{}"))
            case "GET", [entity]:
                return Response(200, as_list(self._search(entity, search_params(params))))
            case "GET", [entity, record_id]:
                return self._read(entity, record_id)
            case "PUT" | "PATCH", [entity, record_id]:
                return self._update(entity, record_id, json.loads(body or b"{}"))
            case "GET", [entity, record_id, link]:
                return Response(200, as_list(self._related(entity, record_id, link, params.get("orderBy"))))
        return Response(404, None)

    def _create(self, entity: str, data: dict) -> Response:
        if any(data.get(field) in (None, "") for field in REQUIRED.get(entity, ())):
            return Response(400, None)
        record = {**data, "id": uuid.uuid4().hex[:17], "createdAt": now()}
        self._records.setdefault(entity, {})[record["id"]] = record
        return Response(200, dict(record))

    def _read(self, entity: str, record_id: str) -> Response:
        record = self._records.get(entity, {}).get(record_id)
        if record is None:
            return Response(404, None)
        return Response(200, dict(record))

    def _update(self, entity: str, record_id: str, data: dict) -> Response:
        record = self._records.get(entity, {}).get(record_id)
        if record is None:
            return Response(404, None)
        record.update(data)
        return Response(200, dict(record))

    def _search(self, entity: str, params: dict) -> list[dict]:
        found = [r for r in self._records.get(entity, {}).values() if matches(r, params.get("where", []))]
        found = ordered(found, params.get("orderBy"), params.get("order"))
        return [dict(r) for r in found[: int(params.get("maxSize") or len(found))]]

    def _related(self, entity: str, record_id: str, link: str, order_by: str | None) -> list[dict]:
        child, parent_field = LINKS[(entity, link)]
        children = [r for r in self._records.get(child, {}).values() if r.get(parent_field) == record_id]
        return [dict(r) for r in ordered(children, order_by)]


def header(request: Request, name: str) -> str | None:
    return next((v for k, v in request.headers.items() if k.lower() == name.lower()), None)


def search_params(params: dict) -> dict:
    """Параметры поиска: JSON в `searchParams` (как scripts/espocrm.py) или `where[i][...]` в query."""
    if "searchParams" in params:
        return json.loads(params["searchParams"])
    where: dict[int, dict] = {}
    for key, value in params.items():
        if key.startswith("where["):
            index, field = key.removeprefix("where[").rstrip("]").split("][")
            where.setdefault(int(index), {})[field] = value
    return {**params, "where": [where[i] for i in sorted(where)]}


def matches(record: dict, where: list[dict]) -> bool:
    for condition in where:
        if condition["type"] != "equals":
            raise NotImplementedError(f"Фейк EspoCRM не знает условие {condition['type']}")
        if record.get(condition["attribute"]) != condition.get("value"):
            return False
    return True


def ordered(records: list[dict], order_by: str | None, order: str | None = None) -> list[dict]:
    if not order_by:
        return list(records)
    return sorted(records, key=lambda r: r.get(order_by) or "", reverse=order == "desc")


def as_list(records: list[dict]) -> dict:
    return {"total": len(records), "list": records}


def now() -> str:
    """Формат даты-времени EspoCRM: UTC, до секунды."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

"""Фейк REST API EspoCRM в фейк-сервере: записи в памяти, CRUD, обязательные поля, поиск
(`equals`, `notEquals`, `in`, `isTrue`, `lessThan`, `greaterThan`, `greaterThanOrEquals`, `linkedWith`), связи.

Подключён к фейк-серверу фикстурой `fake_server` (префикс /espocrm, env n8n ESPOCRM_BASE_URL).
Тест читает записанное через `records(entity)` / `related(...)`, заводит своё через `add(...)`,
недоступность CRM или одной сущности — `unavailable([entity])`, медленную CRM — `slow(entity, seconds)`.
Ответы повторяют настоящую EspoCRM на те же запросы (контракт — tests/test_espocrm.py);
новый вид связи — строка в LINKS.
"""

import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from tests.fake_server import Request, Response

# Значение из docker-compose.test.yml (ESPOCRM_API_KEY n8n стенда).
API_KEY = "test-espocrm-key"
# unavailable() без сущности: лежит вся CRM.
ALL = "*"

# Обязательные поля (entityDefs модуля Uala): без них настоящая EspoCRM отвечает 400.
REQUIRED = {
    "Conversation": ("name", "channel", "senderId"),
    "Message": ("conversationId", "direction", "author", "text"),
    "Vehicle": ("name",),
    "Contact": ("lastName",),
    "Lead": ("lastName",),
}

# Телефон настоящая EspoCRM принимает только в международном формате (+48600123456), иначе 400.
PHONE = re.compile(r"\+[0-9 ()-]+")

# Связь hasMany (сущность, связь) → (связанная сущность, поле со ссылкой на родителя: id или список id).
LINKS = {
    ("Conversation", "messages"): ("Message", "conversationId"),
    ("Contact", "conversations"): ("Conversation", "contactId"),
    ("Contact", "vehicles"): ("Vehicle", "contactId"),
    ("Contact", "leads"): ("Lead", "contactId"),
    ("Vehicle", "leads"): ("Lead", "vehicleId"),
    ("Conversation", "leads"): ("Lead", "conversationId"),
    ("Contact", "meetings"): ("Meeting", "contactsIds"),
    ("Vehicle", "meetings"): ("Meeting", "vehicleId"),
    ("WorkingTimeCalendar", "ranges"): ("WorkingTimeRange", "calendarsIds"),
}


class FakeEspoCrm:
    PREFIX = "/espocrm/api/v1/"

    def __init__(self, api_key: str = API_KEY):
        self._api_key = api_key
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, dict]] = {}
        # Сущности, на запросы к которым CRM отвечает 503; ALL — вся CRM.
        self._unavailable: set[str] = set()
        # Сущность → сколько секунд CRM думает над каждым запросом к ней.
        self._slow: dict[str, float] = {}

    def reset(self):
        with self._lock:
            self._records.clear()
            self._unavailable.clear()
            self._slow.clear()

    @contextmanager
    def unavailable(self, entity: str = ALL):
        """CRM (или одна её сущность) лежит: 503, пока блок не закончится."""
        self._unavailable.add(entity)
        try:
            yield
        finally:
            self._unavailable.discard(entity)

    @contextmanager
    def slow(self, entity: str, seconds: float):
        """Запросы к сущности отвечают через seconds секунд, пока блок не закончится: окно гонки двух вызовов."""
        self._slow[entity] = seconds
        try:
            yield
        finally:
            self._slow.pop(entity, None)

    def add(self, entity: str, data: dict) -> dict:
        """Запись, заведённая в CRM человеком (сотрудник, команда, задача), а не через n8n."""
        with self._lock:
            return self._store(entity, data)

    def change(self, entity: str, record_id: str, data: dict) -> None:
        """Правка записи человеком в CRM (сотрудник перенёс или отменил Запись)."""
        with self._lock:
            self._records[entity][record_id].update(data)

    def records(self, entity: str) -> list[dict]:
        """Записи сущности в порядке создания."""
        with self._lock:
            return [dict(r) for r in self._records.get(entity, {}).values()]

    def related(self, entity: str, record_id: str, link: str, order_by: str | None = None) -> list[dict]:
        with self._lock:
            return self._related(entity, record_id, link, order_by, None)

    def __call__(self, request: Request) -> Response:
        url = urlsplit(request.path)
        parts = url.path.removeprefix(self.PREFIX).split("/")
        if self._unavailable & {ALL, parts[0]}:
            return Response(503, None)
        time.sleep(self._slow.get(parts[0], 0))
        if header(request, "X-Api-Key") != self._api_key:
            return Response(401, None)
        params = {key: values[-1] for key, values in parse_qs(url.query).items()}
        with self._lock:
            return self._route(request.method, parts, params, request.body)

    def _route(self, method: str, parts: list[str], params: dict, body: bytes) -> Response:
        match method, parts:
            case "POST", [entity]:
                return self._create(entity, json.loads(body or b"{}"))
            case "GET", [entity]:
                return Response(200, self._search(entity, search_params(params)))
            case "GET", [entity, record_id]:
                return self._read(entity, record_id)
            case "PUT" | "PATCH", [entity, record_id]:
                return self._update(entity, record_id, json.loads(body or b"{}"))
            case "GET", [entity, record_id, link]:
                related = self._related(entity, record_id, link, params.get("orderBy"), params.get("order"))
                return Response(200, as_list(related))
        return Response(404, None)

    def _create(self, entity: str, data: dict) -> Response:
        if any(data.get(field) in (None, "") for field in REQUIRED.get(entity, ())) or not valid(data):
            return Response(400, None)
        return Response(200, self._store(entity, data))

    def _store(self, entity: str, data: dict) -> dict:
        # createdAt из data — запись, заведённая «в прошлом» (crm.add); n8n его не шлёт.
        record = {"createdAt": now(), **data, "id": uuid.uuid4().hex[:17]}
        self._records.setdefault(entity, {})[record["id"]] = record
        return dict(record)

    def _read(self, entity: str, record_id: str) -> Response:
        record = self._records.get(entity, {}).get(record_id)
        if record is None:
            return Response(404, None)
        return Response(200, dict(record))

    def _update(self, entity: str, record_id: str, data: dict) -> Response:
        record = self._records.get(entity, {}).get(record_id)
        if record is None:
            return Response(404, None)
        if not valid(data):
            return Response(400, None)
        record.update(data)
        return Response(200, dict(record))

    def _search(self, entity: str, params: dict) -> dict:
        """Ответ поиска: total — все совпадения, list — не больше maxSize."""
        found = [r for r in self._records.get(entity, {}).values() if matches(r, params.get("where", []))]
        found = ordered(found, params.get("orderBy"), params.get("order"))
        page = [dict(r) for r in found[: int(params.get("maxSize") or len(found))]]
        return {"total": len(found), "list": page}

    def _related(self, entity: str, record_id: str, link: str, order_by: str | None, order: str | None) -> list[dict]:
        child, parent_field = LINKS[(entity, link)]
        children = [r for r in self._records.get(child, {}).values() if links_to(r.get(parent_field), record_id)]
        return [dict(r) for r in ordered(children, order_by, order)]


def header(request: Request, name: str) -> str | None:
    return next((v for k, v in request.headers.items() if k.lower() == name.lower()), None)


def valid(data: dict) -> bool:
    phone = data.get("phoneNumber")
    return phone in (None, "") or bool(PHONE.fullmatch(phone))


def links_to(parent: str | list | None, record_id: str) -> bool:
    return record_id in parent if isinstance(parent, list) else parent == record_id


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
    return all(condition_matches(record, condition) for condition in where)


def condition_matches(record: dict, condition: dict) -> bool:
    kind, attribute, value = condition["type"], condition["attribute"], condition.get("value")
    if kind == "equals":
        return record.get(attribute) == value
    if kind == "notEquals":
        return record.get(attribute) != value
    # Даты EspoCRM («YYYY-MM-DD HH:MM:SS») сравниваются как строки; пустое поле не подходит.
    if kind == "lessThan":
        return record.get(attribute) is not None and record[attribute] < value
    if kind == "greaterThan":
        return record.get(attribute) is not None and record[attribute] > value
    if kind == "greaterThanOrEquals":
        return record.get(attribute) is not None and record[attribute] >= value
    if kind == "in":
        return record.get(attribute) in value
    if kind == "isTrue":
        return record.get(attribute) is True
    if kind == "linkedWith":
        # Связь многие-ко-многим (User.teams): id связанных записей лежат в <связь>Ids.
        return bool(set(record.get(attribute + "Ids") or []) & set(value))
    raise NotImplementedError(f"Фейк EspoCRM не знает условие {kind}")


def ordered(records: list[dict], order_by: str | None, order: str | None = None) -> list[dict]:
    if not order_by:
        return list(records)
    return sorted(records, key=lambda r: r.get(order_by) or "", reverse=order == "desc")


def as_list(records: list[dict]) -> dict:
    return {"total": len(records), "list": records}


def now() -> str:
    """Формат даты-времени EspoCRM: UTC, до секунды."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

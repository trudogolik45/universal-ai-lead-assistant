"""База знаний Заказчика в фейковой EspoCRM и запрос, которым её читает Ассистент."""

import json
from pathlib import Path

from tests.fake_server import Response

KNOWLEDGE_PATH = "/espocrm/api/v1/KnowledgeItem"
WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "n8n" / "workflows"
LOAD_NODE = "Load knowledge base"


def knowledge_item(name: str, kind: str = "service", description: str | None = None,
                   price: float | None = None, price_from: bool = False) -> dict:
    """Запись KnowledgeItem, как её отдаёт REST API EspoCRM."""
    return {"name": name, "kind": kind, "description": description, "price": price, "priceFrom": price_from}


def respond_with(fake, *knowledge_bases: list[dict] | Response):
    """Ответы EspoCRM на чтение Базы знаний: по одному на входящее Сообщение, последний повторяется."""
    fake.respond("GET", KNOWLEDGE_PATH, *(as_response(kb) for kb in knowledge_bases))


def as_response(knowledge_base: list[dict] | Response) -> Response:
    if isinstance(knowledge_base, Response):
        return knowledge_base
    return Response(200, {"total": len(knowledge_base), "list": knowledge_base})


def knowledge_requests(fake):
    return fake.requests(KNOWLEDGE_PATH)


def assistant_knowledge_query() -> dict[str, str]:
    """Query-параметры узла «Load knowledge base» из workflow репо: контрактный тест шлёт их в настоящую EspoCRM."""
    return node_query(LOAD_NODE)


def node_query(node_name: str) -> dict[str, str]:
    """Query-параметры HTTP-узла n8n по имени, как они записаны в workflow репо."""
    for path in sorted(WORKFLOWS_DIR.glob("*.json")):
        for node in json.loads(path.read_text())["nodes"]:
            if node["name"] == node_name:
                params = node["parameters"]["queryParameters"]["parameters"]
                return {param["name"]: param["value"] for param in params}
    raise LookupError(f"Нет узла «{node_name}» в {WORKFLOWS_DIR}")

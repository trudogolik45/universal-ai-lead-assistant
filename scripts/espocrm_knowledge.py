"""Демо-База знаний автосервиса AutoPro Service в EspoCRM (сущность KnowledgeItem модуля Uala).

Данные — scripts/data/autopro_knowledge.json, польский перевод docs/autopro_service_knowledge_base.md.
Идемпотентно: запись ищется по паре (kind, name), существующие не трогаются — правки Заказчика
в CRM повторный запуск не затирает.

  ESPOCRM_URL=... ESPOCRM_ADMIN_PASSWORD=... uv run python -m scripts.espocrm_knowledge
"""

import json
from pathlib import Path

from scripts.espocrm import EspoCrm, admin_from_env

KNOWLEDGE_FILE = Path(__file__).resolve().parent / "data" / "autopro_knowledge.json"


def seed_knowledge(admin: EspoCrm, path: Path = KNOWLEDGE_FILE) -> int:
    """Создаёт недостающие записи Базы знаний. Возвращает, сколько создано."""
    missing = [item for item in json.loads(path.read_text()) if not exists(admin, item)]
    for item in missing:
        admin.create("KnowledgeItem", item)
    return len(missing)


def exists(admin: EspoCrm, item: dict) -> bool:
    where = [{"type": "equals", "attribute": key, "value": item[key]} for key in ("kind", "name")]
    return bool(admin.find("KnowledgeItem", where, select=["id"]))


def main() -> None:
    print(f"Создано записей Базы знаний: {seed_knowledge(admin_from_env())}")


if __name__ == "__main__":
    main()

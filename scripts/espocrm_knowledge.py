"""Демо-База знаний автосервиса AutoPro Service в EspoCRM: записи KnowledgeItem модуля Uala
и рабочий календарь (встроенный WorkingTimeCalendar), по которому Ассистент считает свободные слоты.

Данные — scripts/data/autopro_knowledge.json, польский перевод docs/autopro_service_knowledge_base.md,
график — раздел 2 там же. Идемпотентно: запись Базы знаний ищется по паре (kind, name), календарь —
по имени; существующие не трогаются — правки Заказчика в CRM повторный запуск не затирает.

  ESPOCRM_URL=... ESPOCRM_ADMIN_PASSWORD=... uv run python -m scripts.espocrm_knowledge
"""

import json
from pathlib import Path

from scripts.espocrm import EspoCrm, admin_from_env

KNOWLEDGE_FILE = Path(__file__).resolve().parent / "data" / "autopro_knowledge.json"
DEMO_CALENDAR = "AutoPro Service"
# Пн–пт 8:00–18:00, сб 9:00–14:00, вс закрыто (weekday0 — воскресенье). Праздники Заказчик
# заводит в CRM исключениями календаря (WorkingTimeRange «Non-working»).
DEMO_CALENDAR_FIELDS = {
    "name": DEMO_CALENDAR,
    "timeZone": "Europe/Warsaw",
    "timeRanges": [["8:00", "18:00"]],
    **{f"weekday{day}": day != 0 for day in range(7)},
    "weekday6TimeRanges": [["9:00", "14:00"]],
}


def seed_knowledge(admin: EspoCrm, path: Path = KNOWLEDGE_FILE) -> int:
    """Создаёт недостающие записи Базы знаний. Возвращает, сколько создано."""
    missing = [item for item in json.loads(path.read_text()) if not exists(admin, item)]
    for item in missing:
        admin.create("KnowledgeItem", item)
    return len(missing)


def seed_calendar(admin: EspoCrm) -> bool:
    """Создаёт рабочий календарь демо-Заказчика, если его ещё нет. Возвращает, создан ли он."""
    where = [{"type": "equals", "attribute": "name", "value": DEMO_CALENDAR}]
    if admin.find("WorkingTimeCalendar", where, select=["id"]):
        return False
    admin.create("WorkingTimeCalendar", DEMO_CALENDAR_FIELDS)
    return True


def exists(admin: EspoCrm, item: dict) -> bool:
    where = [{"type": "equals", "attribute": key, "value": item[key]} for key in ("kind", "name")]
    return bool(admin.find("KnowledgeItem", where, select=["id"]))


def main() -> None:
    admin = admin_from_env()
    print(f"Создано записей Базы знаний: {seed_knowledge(admin)}")
    print(f"Рабочий календарь создан: {'да' if seed_calendar(admin) else 'нет, уже есть'}")


if __name__ == "__main__":
    main()

"""Запись в свободный слот: рабочий календарь и Записи (Meeting) в EspoCRM, слоты в запросе к AI."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tests.knowledge import node_query
from tests.openrouter import completion_requests

TIME_ZONE = ZoneInfo("Europe/Warsaw")
# Узлы переходника CRM (n8n/workflows/crm-adapter-espocrm.json), чьи запросы повторяют контрактные тесты.
WORKING_CALENDAR_NODE = "Find working calendar"
WORKING_RANGES_NODE = "Find working ranges"
MEETING_PATH = "/espocrm/api/v1/Meeting"


def adapter_query(node_name: str) -> dict[str, str]:
    return node_query(node_name)


def busy_where(starts_at: str, ends_at: str) -> list[dict]:
    """Условие переходника CRM «Запись пересекается со слотом»: отменённые (Not Held) слот не занимают."""
    return [
        {"type": "lessThan", "attribute": "dateStart", "value": ends_at},
        {"type": "greaterThan", "attribute": "dateEnd", "value": starts_at},
        {"type": "notEquals", "attribute": "status", "value": "Not Held"},
    ]


def working_calendar(**fields) -> dict:
    """WorkingTimeCalendar, как его отдаёт REST API EspoCRM: график AutoPro (пн–пт 8–18, сб 9–14)."""
    return {
        "name": "AutoPro Service",
        "timeZone": "Europe/Warsaw",
        "timeRanges": [["8:00", "18:00"]],
        **{f"weekday{day}": day != 0 for day in range(7)},
        **{f"weekday{day}TimeRanges": None for day in range(7)},
        "weekday6TimeRanges": [["9:00", "14:00"]],
        **fields,
    }


def next_weekday(weekday: int) -> date:
    """Ближайший день недели (0 — понедельник), начиная с завтра по Варшаве: всегда в пределах недели,
    на которую Ассистент видит слоты."""
    day = datetime.now(TIME_ZONE).date() + timedelta(days=1)
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def slot(day: date, hour: int) -> str:
    """Слот, как его видит Ассистент: местное время Заказчика."""
    return f"{day.isoformat()} {hour:02d}:00"


def utc(local: str, hours: int = 0) -> str:
    """Местное время слота → дата EspoCRM (UTC, до секунды)."""
    moment = datetime.strptime(local, "%Y-%m-%d %H:%M").replace(tzinfo=TIME_ZONE) + timedelta(hours=hours)
    return moment.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")


def meeting(local: str, **fields) -> dict:
    """Запись на час с начала слота, как её заводит сотрудник."""
    return {"name": "Wizyta", "status": "Planned", "dateStart": utc(local), "dateEnd": utc(local, 1), **fields}


def offered_slots(fake) -> list[str]:
    """Слоты, которые n8n дал Ассистенту записать в последнем запросе к AI (enum appointment_start)."""
    schema = completion_requests(fake)[-1]["response_format"]["json_schema"]["schema"]
    return [value for value in schema["properties"]["appointment_start"]["enum"] if value is not None]


def system_prompt(fake) -> str:
    return completion_requests(fake)[-1]["messages"][0]["content"]

"""API-пользователь n8n в EspoCRM: роль с правами и пользователь с API-ключом; группы сотрудников с ролью.

Идемпотентно: роли, пользователь и команды ищутся по имени, права ролей перезаписываются
из ROLE_ACL и STAFF_ACL.
Ключ генерирует EspoCRM при создании пользователя, команда печатает его в stdout —
make espocrm-api-user на VPS сразу пишет его в ~/uala/.env (ESPOCRM_API_KEY).

  ESPOCRM_URL=... ESPOCRM_ADMIN_PASSWORD=... uv run python -m scripts.espocrm_bootstrap
"""

from scripts.espocrm import EspoCrm, admin_from_env

API_USER = "n8n"
ROLE_NAME = "n8n"

# Уровни прав EspoCRM: create/delete — yes|no, read/edit/stream — all|team|own|no.
RECORD_ACCESS = {"create": "yes", "read": "all", "edit": "all", "delete": "no", "stream": "all"}
# Базу знаний правит Заказчик, n8n её только читает.
READ_ONLY = {"create": "no", "read": "all", "edit": "no", "delete": "no", "stream": "no"}
# Сущности, с которыми работает n8n: свои (модуль Uala) и встроенные.
ROLE_ACL = {
    **{
        entity: RECORD_ACCESS
        for entity in (
            "Contact", "Conversation", "Message", "Vehicle", "Lead", "Meeting", "Task", "RepairOrder", "Estimate"
        )
    },
    "KnowledgeItem": READ_ONLY,
    # Назначение Задачи человеку: n8n ищет сотрудников группы и их открытые задачи.
    "Team": {"read": "all"},
    "User": {"read": "all"},
    # Свободные слоты: рабочий календарь и его исключения. Права у встроенного календаря только
    # «да/нет»: «да» — и чтение, и правка, только чтения EspoCRM не даёт; n8n календарь лишь читает.
    "WorkingTimeCalendar": True,
}
# Группы сотрудников (команды EspoCRM) для Задач человеку; сотрудников в них добавляет Заказчик.
TEAMS = ("Administratorzy", "Mechanicy")
STAFF_ROLE_NAME = "Pracownicy"
# Роль групп: сотрудник видит Задачи человеку своей группы (без права чтения EspoCRM не шлёт ему
# уведомление о назначенной задаче), Беседы и Клиентов, пишет в Беседу и ведёт Заказ-наряды и Сметы.
STAFF_ACL = {
    "Task": {"create": "yes", "read": "team", "edit": "team", "delete": "no", "stream": "team"},
    **{
        entity: RECORD_ACCESS
        for entity in ("Contact", "Conversation", "Message", "Vehicle", "Lead", "Meeting", "RepairOrder", "Estimate")
    },
    "KnowledgeItem": READ_ONLY,
}


def bootstrap(admin: EspoCrm) -> str:
    """Группы сотрудников и API-пользователь n8n; возвращает его API-ключ."""
    ensure_teams(admin)
    return ensure_api_user(admin)


def ensure_teams(admin: EspoCrm) -> None:
    team = {"rolesIds": [ensure_role(admin, STAFF_ROLE_NAME, STAFF_ACL)]}
    for name in TEAMS:
        team_id = find_id(admin, "Team", "name", name)
        if team_id:
            admin.update("Team", team_id, team)
        else:
            admin.create("Team", {"name": name, **team})


def ensure_api_user(admin: EspoCrm) -> str:
    """API-ключ пользователя n8n; роль и пользователь создаются, если их ещё нет."""
    role_id = ensure_role(admin, ROLE_NAME, ROLE_ACL)
    user_id = find_id(admin, "User", "userName", API_USER)
    if user_id:
        admin.update("User", user_id, {"rolesIds": [role_id], "isActive": True})
    else:
        user_id = admin.create(
            "User",
            {"userName": API_USER, "type": "api", "authMethod": "ApiKey", "isActive": True, "rolesIds": [role_id]},
        )["id"]
    return admin.read("User", user_id)["apiKey"]


def ensure_role(admin: EspoCrm, name: str, acl: dict) -> str:
    role = {"name": name, "data": acl, "assignmentPermission": "all"}
    role_id = find_id(admin, "Role", "name", name)
    if role_id:
        admin.update("Role", role_id, role)
        return role_id
    return admin.create("Role", role)["id"]


def find_id(admin: EspoCrm, entity: str, attribute: str, value: str) -> str | None:
    found = admin.find(entity, [{"type": "equals", "attribute": attribute, "value": value}], select=["id"])
    return found[0]["id"] if found else None


def main() -> None:
    print(bootstrap(admin_from_env()))


if __name__ == "__main__":
    main()

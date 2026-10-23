"""API-пользователь n8n в EspoCRM: роль с правами и пользователь с API-ключом.

Идемпотентно: роль и пользователь ищутся по имени, права роли перезаписываются из ROLE_ACL.
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
        for entity in ("Contact", "Conversation", "Message", "Vehicle", "Lead", "Meeting", "Task")
    },
    "KnowledgeItem": READ_ONLY,
}


def ensure_api_user(admin: EspoCrm) -> str:
    """API-ключ пользователя n8n; роль и пользователь создаются, если их ещё нет."""
    role_id = ensure_role(admin)
    user_id = find_id(admin, "User", "userName", API_USER)
    if user_id:
        admin.update("User", user_id, {"rolesIds": [role_id], "isActive": True})
    else:
        user_id = admin.create(
            "User",
            {"userName": API_USER, "type": "api", "authMethod": "ApiKey", "isActive": True, "rolesIds": [role_id]},
        )["id"]
    return admin.read("User", user_id)["apiKey"]


def ensure_role(admin: EspoCrm) -> str:
    role = {"name": ROLE_NAME, "data": ROLE_ACL, "assignmentPermission": "all"}
    role_id = find_id(admin, "Role", "name", ROLE_NAME)
    if role_id:
        admin.update("Role", role_id, role)
        return role_id
    return admin.create("Role", role)["id"]


def find_id(admin: EspoCrm, entity: str, attribute: str, value: str) -> str | None:
    found = admin.find(entity, [{"type": "equals", "attribute": attribute, "value": value}], select=["id"])
    return found[0]["id"] if found else None


def main() -> None:
    print(ensure_api_user(admin_from_env()))


if __name__ == "__main__":
    main()

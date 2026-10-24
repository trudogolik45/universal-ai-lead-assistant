"""Клиент REST API EspoCRM (/api/v1): записи сущностей, поиск, связанные записи.

Авторизация — API-ключ (X-Api-Key, как у n8n) или логин и пароль администратора (Basic):
ключ API-пользователя создаёт только администратор, см. scripts/espocrm_bootstrap.py.
"""

import json
import os

import httpx

TIMEOUT = 30


class EspoCrmError(Exception):
    pass


class EspoCrm:
    def __init__(self, base_url: str, *, api_key: str | None = None, admin: tuple[str, str] | None = None):
        headers = {"X-Api-Key": api_key} if api_key else {}
        self.http = httpx.Client(base_url=f"{base_url.rstrip('/')}/api/v1", headers=headers, auth=admin, timeout=TIMEOUT)

    def request(self, method: str, path: str, **kwargs) -> dict:
        response = self.http.request(method, path, **kwargs)
        if response.is_error:
            # Причину ошибки Espo кладёт в заголовок, тело часто пустое.
            reason = response.headers.get("X-Status-Reason", "")
            raise EspoCrmError(f"{method} {path}: {response.status_code} {reason} {response.text[:500]}".rstrip())
        return response.json()

    def create(self, entity: str, data: dict) -> dict:
        # Без заголовка Espo отвечает 409 на похожую запись (Contact с тем же именем или телефоном).
        return self.request("POST", entity, json=data, headers={"X-Skip-Duplicate-Check": "true"})

    def read(self, entity: str, record_id: str) -> dict:
        return self.request("GET", f"{entity}/{record_id}")

    def update(self, entity: str, record_id: str, data: dict) -> dict:
        return self.request("PUT", f"{entity}/{record_id}", json=data)

    def find(self, entity: str, where: list[dict], **params) -> list[dict]:
        """Записи по условиям where: [{"type": "equals", "attribute": ..., "value": ...}]."""
        search = json.dumps({"where": where, **params})
        return self.request("GET", entity, params={"searchParams": search})["list"]

    def related(self, entity: str, record_id: str, link: str) -> list[dict]:
        return self.request("GET", f"{entity}/{record_id}/{link}")["list"]


def admin_from_env() -> EspoCrm:
    """Клиент администратора по env: ESPOCRM_URL, ESPOCRM_ADMIN_PASSWORD, ESPOCRM_ADMIN_USERNAME (admin)."""
    return EspoCrm(
        os.environ["ESPOCRM_URL"],
        admin=(os.environ.get("ESPOCRM_ADMIN_USERNAME", "admin"), os.environ["ESPOCRM_ADMIN_PASSWORD"]),
    )

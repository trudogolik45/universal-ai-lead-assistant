"""Credentials n8n из env: в репо они не лежат, генерируются при импорте.

Запуск: DATABASE_URL=postgresql://... SMTP_HOST=... uv run python -m scripts.n8n_credentials > credentials.json
Затем внутри контейнера n8n: n8n import:credentials --input=credentials.json
id совпадают с теми, на которые ссылаются workflow из n8n/workflows.
"""

import json
import os
from urllib.parse import parse_qs, unquote, urlsplit

POSTGRES_CREDENTIAL_ID = "uala0postgres001"
SMTP_CREDENTIAL_ID = "uala0smtp0000001"
# Как в libpq: только verify-* проверяют сертификат. Supabase pooler подписан своим CA.
# n8n включает TLS при allowUnauthorizedCerts даже с ssl=disable, поэтому для disable — False.
VERIFYING_SSLMODES = {"verify-ca", "verify-full"}


def postgres_credential(database_url: str) -> dict:
    url = urlsplit(database_url)
    # Supabase требует TLS; локальный Postgres стенда — ?sslmode=disable в URL.
    sslmode = parse_qs(url.query).get("sslmode", ["require"])[0]
    verify = sslmode in VERIFYING_SSLMODES
    return {
        "id": POSTGRES_CREDENTIAL_ID,
        "name": "Supabase",
        "type": "postgres",
        "data": {
            "host": url.hostname,
            "port": url.port or 5432,
            "database": url.path.lstrip("/"),
            "user": unquote(url.username or ""),
            "password": unquote(url.password or ""),
            "ssl": "require" if verify else sslmode,
            "allowUnauthorizedCerts": not verify and sslmode != "disable",
        },
    }


def smtp_credential(env: dict[str, str]) -> dict:
    """SMTP для писем владельцу (отчёты). SMTP_SECURE=true — TLS сразу (порт 465), иначе STARTTLS (587)."""
    secure = env.get("SMTP_SECURE", "").lower() == "true"
    return {
        "id": SMTP_CREDENTIAL_ID,
        "name": "SMTP",
        "type": "smtp",
        "data": {
            "host": env.get("SMTP_HOST", ""),
            "port": int(env.get("SMTP_PORT") or (465 if secure else 587)),
            "secure": secure,
            "user": env.get("SMTP_USER", ""),
            "password": env.get("SMTP_PASSWORD", ""),
        },
    }


def credentials(env: dict[str, str]) -> list[dict]:
    return [postgres_credential(env["DATABASE_URL"]), smtp_credential(env)]


if __name__ == "__main__":
    print(json.dumps(credentials(dict(os.environ)), indent=2))

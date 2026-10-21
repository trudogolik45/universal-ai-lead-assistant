"""Применяет SQL-миграции из supabase/migrations к базе по DATABASE_URL.

Запуск: DATABASE_URL=postgresql://... uv run python -m scripts.migrate
"""

import os
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"


def migrate(database_url: str) -> list[str]:
    """Применяет ещё не применённые миграции по порядку имён. Возвращает их имена."""
    applied_now = []
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "create table if not exists schema_migrations ("
            " version text primary key,"
            " applied_at timestamptz not null default now())"
        )
        applied = {row[0] for row in conn.execute("select version from schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            conn.execute(path.read_text())
            conn.execute("insert into schema_migrations (version) values (%s)", (path.name,))
            applied_now.append(path.name)
    return applied_now


if __name__ == "__main__":
    for name in migrate(os.environ["DATABASE_URL"]):
        print(f"applied {name}")

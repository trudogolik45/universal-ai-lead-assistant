"""Заливает демо-профили Заказчиков из supabase/seed и привязывает их к Каналам из env.

Запуск: DATABASE_URL=postgresql://... uv run python -m scripts.seed
Необязательные env: DEMO_MESSENGER_PAGE_ID (страница демо-Заказчика),
TELEGRAM_CHAT_ID и GOOGLE_SHEETS_SPREADSHEET_ID (Канал доставки всех сид-профилей).
"""

import os
from pathlib import Path

import psycopg
from psycopg import sql

SEED_DIR = Path(__file__).resolve().parent.parent / "supabase" / "seed"
DEMO_COMPANY_SLUG = "uniwersalny-serwis"
SEED_COMPANY_SLUGS = (DEMO_COMPANY_SLUG, "lsniace-auto", "remont-pro")


def seed(database_url, demo_page_id=None, telegram_chat_id=None, spreadsheet_id=None):
    """Идемпотентно создаёт сид-профили и применяет переданные привязки."""
    with psycopg.connect(database_url) as conn:
        for path in sorted(SEED_DIR.glob("*.sql")):
            conn.execute(path.read_text())
        if demo_page_id:
            conn.execute(
                "update companies set messenger_page_id = %s where slug = %s",
                (demo_page_id, DEMO_COMPANY_SLUG),
            )
        bind_delivery(conn, "telegram_chat_id", telegram_chat_id)
        bind_delivery(conn, "sheets_spreadsheet_id", spreadsheet_id)


def bind_delivery(conn, column, value):
    if not value:
        return
    query = sql.SQL("update companies set {} = %s where slug = any(%s)").format(sql.Identifier(column))
    conn.execute(query, (value, list(SEED_COMPANY_SLUGS)))


if __name__ == "__main__":
    seed(
        os.environ["DATABASE_URL"],
        demo_page_id=os.environ.get("DEMO_MESSENGER_PAGE_ID"),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
        spreadsheet_id=os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID"),
    )

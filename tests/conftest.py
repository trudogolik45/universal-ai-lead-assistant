import os

import psycopg
import pytest

from scripts.migrate import migrate

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def database_url():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL не задан: нужен пустой Postgres, схема public будет пересоздана")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("drop schema public cascade; create schema public;")
    migrate(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("truncate companies cascade")
        yield conn

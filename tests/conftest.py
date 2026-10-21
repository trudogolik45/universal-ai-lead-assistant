import os

import psycopg
import pytest

from scripts.migrate import migrate
from tests.fake_server import FakeServer
from tests.stand import Stand, docker_available


@pytest.fixture(scope="session")
def stand():
    """Стенд docker-compose.test.yml. STAND_KEEP=1 оставляет контейнеры после прогона."""
    if not docker_available():
        pytest.skip("Нет Docker: тестовый стенд не поднять")
    stand = Stand()
    yield stand
    if not os.environ.get("STAND_KEEP"):
        stand.down()


@pytest.fixture(scope="session")
def database_url(stand):
    """Postgres стенда с чистой схемой: public пересоздаётся, миграции применяются заново."""
    url = stand.up_postgres()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop schema public cascade; create schema public;")
    migrate(url)
    return url


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("truncate companies cascade")
        yield conn


@pytest.fixture(scope="session")
def fake_server():
    server = FakeServer().start()
    yield server
    server.stop()


@pytest.fixture
def fake(fake_server):
    """Фейк внешних API без заданных ответов и записанных запросов."""
    fake_server.reset()
    return fake_server


@pytest.fixture(scope="session")
def n8n_url(stand, database_url, fake_server):
    """n8n стенда со всеми workflow из n8n/workflows, внешние API смотрят на фейк."""
    return stand.up_n8n(fake_server.base_urls())

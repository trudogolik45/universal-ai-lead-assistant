import os

import psycopg
import pytest

from scripts.migrate import migrate
from tests.fake_server import FakeServer
from tests.google import ServiceAccount
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
        conn.execute("truncate companies, inbox cascade")
        yield conn


@pytest.fixture(scope="session")
def fake_server():
    server = FakeServer().start()
    yield server
    server.stop()


@pytest.fixture
def fake(fake_server):
    """Фейк внешних API без заданных ответов и записанных запросов.
    Сброс и после теста: заданные ответы не утекают в тесты, которые фейк не берут."""
    fake_server.reset()
    yield fake_server
    fake_server.reset()


@pytest.fixture(scope="session")
def service_account():
    """Service account Google стенда: ключ свой на прогон, фейк проверяет им подпись JWT."""
    return ServiceAccount.generate()


@pytest.fixture(scope="session")
def n8n_url(stand, database_url, fake_server, service_account):
    """n8n стенда со всеми workflow из n8n/workflows, внешние API смотрят на фейк."""
    return stand.up_n8n({**fake_server.base_urls(), **service_account.env()})

import os

import psycopg
import pytest

from scripts.migrate import migrate
from tests.espocrm import EMPLOYEE_REPLY_PATH, TASK_DONE_PATH
from tests.fake_espocrm import FakeEspoCrm
from tests.fake_server import FakeServer
from tests.mailpit import Mailpit
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
        truncate(conn)
        yield conn


def truncate(conn, attempts: int = 3):
    """Чистые таблицы к началу теста. Хвост обработки предыдущего теста в n8n может ещё писать
    в них: Postgres снимает truncate как жертву deadlock — повторяем."""
    for attempt in range(1, attempts + 1):
        try:
            conn.execute("truncate companies, inbox cascade")
            return
        except psycopg.errors.DeadlockDetected:
            if attempt == attempts:
                raise


@pytest.fixture(scope="session")
def espocrm(stand, fake_server):
    """Настоящая EspoCRM стенда (tests/espocrm.py): своя база в Postgres стенда, свежая установка
    на прогон, модуль Uala и API-пользователь n8n, как в проде. Ответ сотрудника и закрытую
    Задачу хуки шлют в фейк-сервер, а не в n8n. Записи между тестами не чистятся: тест создаёт свои."""
    return stand.up_espocrm({
        "EMPLOYEE_REPLY_URL": fake_server.container_url(EMPLOYEE_REPLY_PATH),
        "TASK_DONE_URL": fake_server.container_url(TASK_DONE_PATH),
    })


@pytest.fixture(scope="session")
def fake_server(fake_espocrm):
    server = FakeServer().start()
    server.mount(FakeEspoCrm.PREFIX, fake_espocrm)
    yield server
    server.stop()


@pytest.fixture
def fake(fake_server):
    """Фейк внешних API без заданных ответов и записанных запросов; фейковая EspoCRM пуста
    (её База знаний — тоже). Сброс и после теста: заданные ответы не утекают в тесты, которые фейк не берут."""
    fake_server.reset()
    yield fake_server
    fake_server.reset()


@pytest.fixture(scope="session")
def fake_espocrm():
    return FakeEspoCrm()


@pytest.fixture
def crm(fake, fake_espocrm):
    """Фейковая EspoCRM (tests/fake_espocrm.py), пустая к началу теста: что записал n8n."""
    return fake_espocrm


@pytest.fixture(scope="session")
def n8n_url(stand, database_url, fake_server):
    """n8n стенда со всеми workflow из n8n/workflows, внешние API смотрят на фейк."""
    return stand.up_n8n(fake_server.base_urls())


@pytest.fixture
def mailpit(stand, n8n_url):
    """Письма, отправленные n8n стенда (tests/mailpit.py); к началу теста ящик пуст."""
    mailpit = Mailpit(stand.mailpit_url())
    mailpit.clear()
    return mailpit

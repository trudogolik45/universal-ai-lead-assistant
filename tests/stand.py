"""Тестовый стенд: docker-compose.test.yml (Postgres, n8n, EspoCRM), импорт workflow и credentials.

Порядок: Postgres → миграции (фикстура `database_url`) → n8n с базовыми URL фейк-сервера →
scripts.n8n_sync.push, как в проде: credentials, импорт и публикация всех n8n/workflows/*.json,
перезапуск n8n (вебхуки опубликованных workflow регистрируются при старте).
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import psycopg

from scripts.espocrm import EspoCrm
from scripts.espocrm_bootstrap import ensure_api_user
from scripts.n8n_sync import WORKFLOWS_DIR, push
from tests.espocrm import ESPOCRM_ADMIN, EspoCrmStand

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "docker-compose.test.yml"

# Учётка Postgres из docker-compose.test.yml.
PG_AUTH = "test:test"
# Метод пробы регистрации вебхуков: в workflow его не используем.
PROBE_METHOD = "PUT"
# EspoCRM: своя база в Postgres стенда, основной контейнер, cron-задачи и WebSocket.
ESPOCRM_DATABASE = "espocrm"
ESPOCRM_SERVICES = ("espocrm", "espocrm-daemon", "espocrm-websocket")


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def default_project_name() -> str:
    """Своё имя compose-проекта на каждый checkout: параллельные стенды не пересекаются."""
    return "uala-test-" + hashlib.sha1(str(ROOT).encode()).hexdigest()[:8]


class Stand:
    def __init__(self, project: str | None = None):
        self.project = project or os.environ.get("COMPOSE_PROJECT_NAME") or default_project_name()
        self.env: dict[str, str] = {}

    def compose(self, *args: str, input: str | None = None) -> str:
        result = subprocess.run(
            ["docker", "compose", "-p", self.project, "-f", str(COMPOSE_FILE), *args],
            input=input,
            capture_output=True,
            text=True,
            env={**os.environ, **self.env},
        )
        if result.returncode != 0:
            raise RuntimeError(f"docker compose {' '.join(args)}:\n{result.stdout}\n{result.stderr}")
        return result.stdout

    def host_url(self, service: str, port: int) -> str:
        """host:port, на который Docker пробросил порт сервиса (порты стенда случайные)."""
        return self.compose("port", service, str(port)).strip()

    def up_postgres(self) -> str:
        self.compose("up", "-d", "--wait", "postgres")
        url = f"postgresql://{PG_AUTH}@{self.host_url('postgres', 5432)}/test"
        wait_until(lambda: accepts_connections(url), f"Postgres {url}")
        return url

    def up_n8n(self, env: dict[str, str]) -> str:
        """Поднимает n8n с env (базовые URL внешних API, ключи) и публикует все workflow. Возвращает URL n8n."""
        self.env.update(env)
        self.compose("up", "-d", "--force-recreate", "n8n")
        wait_ready(self.n8n_url())
        push(self)
        url = self.n8n_url()
        wait_ready(url)
        wait_webhooks(url)
        return url

    def up_espocrm(self) -> EspoCrmStand:
        """EspoCRM с нуля: пустая база `espocrm` в Postgres стенда, установка, API-пользователь n8n."""
        recreate_database(self.up_postgres(), ESPOCRM_DATABASE)
        self.compose("up", "-d", "--build", "--force-recreate", "--renew-anon-volumes", "--wait", *ESPOCRM_SERVICES)
        url = f"http://{self.host_url('espocrm', 80)}"
        admin = EspoCrm(url, admin=ESPOCRM_ADMIN)
        # Healthcheck смотрит статику; первый запрос к API собирает кэш и под нагрузкой идёт долго.
        wait_until(lambda: admin.http.get("App/user").status_code == 200, f"API EspoCRM {url}", timeout=300)
        api = EspoCrm(url, api_key=ensure_api_user(admin))
        return EspoCrmStand(url, admin, api, websocket=self.host_url("espocrm-websocket", 8080))

    def n8n_url(self) -> str:
        # Спрашивать после каждого (пере)запуска: случайный порт хоста меняется.
        return f"http://{self.host_url('n8n', 5678)}"

    def run(self, command: str, input: str | None = None) -> str:
        """CLI в контейнере n8n стенда (интерфейс scripts.n8n_sync.N8n)."""
        return self.compose("exec", "-T", "n8n", "sh", "-c", command, input=input)

    def restart(self) -> None:
        self.compose("restart", "n8n")

    def down(self):
        self.compose("down", "-v", "--remove-orphans")


def accepts_connections(url: str) -> bool:
    """pg_isready проходит и на временном сервере initdb, который TCP не слушает."""
    with psycopg.connect(url, connect_timeout=2):
        return True


def recreate_database(url: str, name: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"drop database if exists {name} with (force)")
        conn.execute(f"create database {name}")


def wait_until(probe, what: str, timeout: float = 90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except (httpx.TransportError, psycopg.OperationalError):
            pass
        time.sleep(0.5)
    raise TimeoutError(f"не дождались за {timeout} с: {what}")


def wait_ready(url: str):
    # Первый старт n8n — миграции его базы; рядом с другими стендами они идут дольше 90 с.
    wait_until(
        lambda: httpx.get(f"{url}/healthz/readiness", timeout=2).status_code == 200,
        f"n8n {url}",
        timeout=300,
    )


def webhook_paths() -> set[str]:
    return {
        node["parameters"]["path"]
        for path in WORKFLOWS_DIR.glob("*.json")
        for node in json.loads(path.read_text())["nodes"]
        if node["type"] == "n8n-nodes-base.webhook"
    }


def webhook_registered(url: str, path: str) -> bool:
    """Readiness n8n не ждёт регистрации вебхуков. Пробуем путь методом, которого у него нет:
    зарегистрированный путь отвечает «not registered for PUT requests», незнакомый —
    «The requested webhook ... is not registered». Обработку workflow проба не запускает."""
    response = httpx.request(PROBE_METHOD, f"{url}/webhook/{path}", timeout=2)
    return "requested webhook" not in response.text


def wait_webhooks(url: str):
    for path in webhook_paths():
        wait_until(lambda: webhook_registered(url, path), f"вебхук /webhook/{path}")

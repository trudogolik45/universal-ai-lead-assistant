"""Тестовый стенд: docker-compose.test.yml (Postgres + n8n), импорт workflow и credentials.

Порядок: Postgres → миграции (фикстура `database_url`) → n8n с базовыми URL фейк-сервера →
credentials (scripts/n8n_credentials.py) → импорт и публикация всех n8n/workflows/*.json → перезапуск n8n
(вебхуки опубликованных workflow регистрируются при старте).
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from scripts.n8n_credentials import credentials

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "docker-compose.test.yml"
WORKFLOWS_DIR = ROOT / "n8n" / "workflows"

# Учётка Postgres из docker-compose.test.yml. Изнутри сети compose он — хост `postgres`.
PG_AUTH = "test:test"
N8N_DATABASE_URL = f"postgresql://{PG_AUTH}@postgres:5432/test?sslmode=disable"
# Метод пробы регистрации вебхуков: в workflow его не используем.
PROBE_METHOD = "PUT"


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def default_project_name() -> str:
    """Своё имя compose-проекта на каждый checkout: параллельные стенды не пересекаются."""
    return "uala-test-" + hashlib.sha1(str(ROOT).encode()).hexdigest()[:8]


class Stand:
    def __init__(self):
        self.project = os.environ.get("COMPOSE_PROJECT_NAME") or default_project_name()
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
        return f"postgresql://{PG_AUTH}@{self.host_url('postgres', 5432)}/test"

    def up_n8n(self, base_urls: dict[str, str]) -> str:
        """Поднимает n8n с базовыми URL внешних API и публикует все workflow. Возвращает URL n8n."""
        self.env.update(base_urls)
        self.compose("up", "-d", "--force-recreate", "n8n")
        wait_ready(self.n8n_url())
        self.import_credentials()
        self.import_workflows()
        self.compose("restart", "n8n")
        url = self.n8n_url()
        wait_ready(url)
        wait_webhooks(url)
        return url

    def n8n_url(self) -> str:
        # Спрашивать после каждого (пере)запуска: случайный порт хоста меняется.
        return f"http://{self.host_url('n8n', 5678)}"

    def n8n_cli(self, command: str, input: str | None = None) -> str:
        return self.compose("exec", "-T", "n8n", "sh", "-c", command, input=input)

    def import_credentials(self):
        self.n8n_cli(
            "cat > /tmp/credentials.json && n8n import:credentials --input=/tmp/credentials.json",
            input=json.dumps(credentials(N8N_DATABASE_URL)),
        )

    def import_workflows(self):
        self.n8n_cli("n8n import:workflow --separate --input=/workflows")
        for path in sorted(WORKFLOWS_DIR.glob("*.json")):
            workflow_id = json.loads(path.read_text())["id"]
            self.n8n_cli(f"n8n publish:workflow --id={workflow_id}")

    def down(self):
        self.compose("down", "-v", "--remove-orphans")


def wait_until(probe, what: str, timeout: float = 90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"не дождались за {timeout} с: {what}")


def wait_ready(url: str):
    wait_until(
        lambda: httpx.get(f"{url}/healthz/readiness", timeout=2).status_code == 200,
        f"n8n {url}",
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

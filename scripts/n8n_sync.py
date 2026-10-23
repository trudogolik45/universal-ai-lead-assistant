"""Синхронизация workflow между репо (n8n/workflows) и n8n.

push — credentials из env контейнера n8n (scripts/n8n_credentials.py), импорт всех workflow,
       publish:workflow каждого и перезапуск n8n: вебхуки регистрируются только при старте.
pull — экспорт всех workflow обратно в репо в формате репо, без данных прогонов. Если в JSON
       нашлось значение секрета из env n8n, экспорт останавливается и ничего не пишет.

Прод (VPS n3-vps, compose в ~/uala): make workflows / make workflows-export, или
  uv run python -m scripts.n8n_sync push --host n3-vps --dir uala
Тестовый стенд использует те же push/pull (tests/stand.py).
"""

import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from scripts.n8n_credentials import credentials

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = ROOT / "n8n" / "workflows"

# Ключи workflow, которые лежат в репо. Остальное (pinData, staticData, versionId, даты,
# meta, tags, shared) — данные конкретного n8n и прогонов.
REPO_KEYS = ("id", "name", "active", "settings", "nodes", "connections")

# Переменные .env с секретами (см. .env.example): их значений не должно быть в экспорте.
SECRET_ENV = (
    "N8N_ENCRYPTION_KEY",
    "DATABASE_URL",
    "OPENROUTER_API_KEY",
    "META_APP_SECRET",
    "META_VERIFY_TOKEN",
    "META_PAGE_ACCESS_TOKEN",
    "WHATSAPP_ACCESS_TOKEN",
    "INSTAGRAM_ACCESS_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "RETRY_WEBHOOK_SECRET",
    "ESPOCRM_DB_PASSWORD",
    "ESPOCRM_ADMIN_PASSWORD",
    "ESPOCRM_API_KEY",
    "EMPLOYEE_REPLY_SECRET",
    "REPORT_WEBHOOK_SECRET",
    "SMTP_PASSWORD",
)

# Короче — не ищем: короткая строка («test») встречается в любом JSON и даёт ложную тревогу.
MIN_SECRET_LENGTH = 8

TMP_FILE = "/tmp/uala-sync.json"


class N8n(Protocol):
    """Где выполнять CLI n8n: контейнер стенда или прода."""

    def run(self, command: str, input: str | None = None) -> str: ...

    def restart(self) -> None: ...


class SecretLeak(Exception):
    pass


class Vps:
    """n8n прод-стека: compose-проект в ~/<directory> на ssh-хосте."""

    def __init__(self, host: str, directory: str):
        self.host = host
        self.directory = directory

    def ssh(self, remote: str, input: str | None = None) -> str:
        result = subprocess.run(
            ["ssh", self.host, f"cd {shlex.quote(self.directory)} && {remote}"],
            input=input,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ssh {self.host}: {result.stderr.strip()}")
        return result.stdout

    def run(self, command: str, input: str | None = None) -> str:
        return self.ssh(f"docker compose exec -T n8n sh -c {shlex.quote(command)}", input)

    def restart(self) -> None:
        self.ssh("docker compose restart n8n")


def container_env(n8n: N8n) -> dict[str, str]:
    """Env контейнера n8n целиком (там же .env): значения не печатаются."""
    return json.loads(n8n.run("node -e 'process.stdout.write(JSON.stringify(process.env))'"))


def secret_values(env: dict[str, str]) -> dict[str, str]:
    secrets = {name: env.get(name, "") for name in SECRET_ENV}
    password = urlsplit(secrets["DATABASE_URL"]).password if secrets["DATABASE_URL"] else None
    secrets["DATABASE_URL (пароль)"] = password or ""
    return secrets


def push(n8n: N8n, workflows_dir: Path = WORKFLOWS_DIR) -> None:
    env = container_env(n8n)
    if not env.get("DATABASE_URL"):
        raise SystemExit("В env n8n нет DATABASE_URL: credentials Postgres не из чего собрать")
    import_file(n8n, "import:credentials", json.dumps(credentials(env)))
    paths = sorted(workflows_dir.glob("*.json"))
    for path in paths:
        import_file(n8n, "import:workflow", path.read_text())
    for path in paths:
        n8n.run(f"n8n publish:workflow --id={shlex.quote(json.loads(path.read_text())['id'])}")
    n8n.restart()


def import_file(n8n: N8n, command: str, content: str) -> None:
    """Файл передаётся через stdin, а не аргументом: секреты не попадают в списки процессов."""
    n8n.run(f"cat > {TMP_FILE} && n8n {command} --input={TMP_FILE}; status=$?; rm -f {TMP_FILE}; exit $status", content)


def pull(n8n: N8n, workflows_dir: Path = WORKFLOWS_DIR) -> list[Path]:
    secrets = secret_values(container_env(n8n))
    n8n.run(f"n8n export:workflow --all --output={TMP_FILE}")
    exported = json.loads(n8n.run(f"cat {TMP_FILE}; rm -f {TMP_FILE}"))
    workflows = [repo_workflow(workflow, secrets) for workflow in exported]
    names = repo_file_names()
    written = []
    for workflow in workflows:
        path = workflows_dir / names.get(workflow["id"], slug(workflow["name"]) + ".json")
        path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n")
        written.append(path)
    return written


def repo_workflow(exported: dict, secrets: dict[str, str]) -> dict:
    """Workflow в формате репо. Неактивен: включает его push через publish:workflow."""
    workflow = {key: exported[key] for key in REPO_KEYS}
    workflow["active"] = False
    text = json.dumps(workflow, ensure_ascii=False)
    leaked = [name for name, value in secrets.items() if len(value) >= MIN_SECRET_LENGTH and value in text]
    if leaked:
        raise SecretLeak(f"workflow {workflow['name']!r} содержит значение {', '.join(leaked)}")
    return workflow


def repo_file_names() -> dict[str, str]:
    """id workflow → имя файла в репо: экспорт перезаписывает те же файлы."""
    return {json.loads(path.read_text())["id"]: path.name for path in WORKFLOWS_DIR.glob("*.json")}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("push", "pull"))
    parser.add_argument("--host", default="n3-vps", help="ssh-хост VPS")
    parser.add_argument("--dir", default="uala", help="каталог compose-проекта на VPS")
    args = parser.parse_args()
    n8n = Vps(args.host, args.dir)
    if args.action == "push":
        push(n8n)
        print("Workflow импортированы, опубликованы, n8n перезапущен")
        return
    for path in pull(n8n):
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()

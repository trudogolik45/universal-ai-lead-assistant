"""Синхронизация workflow репо и n8n (scripts/n8n_sync.py).

Импорт (`push`) проверяет каждый прогон: стенд поднимается им самим (tests/stand.py).
Здесь — экспорт (`pull`) обратно в репо.
"""

import pytest

from scripts.n8n_sync import SecretLeak, pull, repo_workflow, run_cli
from tests.stand import WORKFLOWS_DIR

# Секреты стенда из docker-compose.test.yml.
STAND_SECRETS = [
    "test-stand-encryption-key",
    "test-app-secret",
    "test-verify-token",
    "test-page-token",
    "test-whatsapp-token",
    "test-instagram-token",
    "test-smsapi-token",
    "test-openrouter-key",
    "test-telegram-token",
    "test-retry-secret",
    "test-espocrm-key",
    "test-n8n-hook-secret",
    "test-report-secret",
    "test-smtp-password",
    "postgresql://test:test@",
]


def test_export_from_n8n_reproduces_repo_workflows_byte_for_byte(stand, n8n_url, tmp_path):
    pull(stand, tmp_path)

    exported = {path.name: path.read_text() for path in tmp_path.glob("*.json")}
    assert exported == {path.name: path.read_text() for path in WORKFLOWS_DIR.glob("*.json")}


def test_export_from_n8n_carries_no_secrets(stand, n8n_url, tmp_path):
    pull(stand, tmp_path)

    text = "".join(path.read_text() for path in tmp_path.glob("*.json"))
    assert text
    assert [secret for secret in STAND_SECRETS if secret in text] == []


def test_export_drops_run_data_and_keeps_workflow_inactive():
    exported = {
        "id": "wf1", "name": "Demo", "active": True, "versionId": "v-1",
        "createdAt": "2026-01-01", "updatedAt": "2026-01-02",
        "settings": {"executionOrder": "v1"}, "nodes": [], "connections": {},
        "pinData": {"Webhook": [{"json": {"text": "dane klienta"}}]},
        "staticData": {"cursor": 1}, "meta": {"instanceId": "abc"}, "tags": [],
    }

    workflow = repo_workflow(exported, secrets={})

    assert workflow == {
        "id": "wf1", "name": "Demo", "active": False,
        "settings": {"executionOrder": "v1"}, "nodes": [], "connections": {},
    }


class BusyN8n:
    """n8n, чей работающий сервер первые busy вызовов CLI держит SQLite."""

    def __init__(self, busy: int):
        self.busy = busy
        self.commands: list[str] = []

    def run(self, command: str, input: str | None = None) -> str:
        self.commands.append(command)
        if len(self.commands) <= self.busy:
            raise RuntimeError("QueryFailedError: SQLITE_BUSY: database is locked")
        return ""


def test_cli_command_is_repeated_while_n8n_database_is_locked():
    n8n = BusyN8n(busy=2)

    run_cli(n8n, "n8n publish:workflow --id=wf1", pause=0)

    assert n8n.commands == ["n8n publish:workflow --id=wf1"] * 3


def test_cli_command_failing_otherwise_is_not_repeated():
    class Broken(BusyN8n):
        def run(self, command, input=None):
            self.commands.append(command)
            raise RuntimeError("Workflow not found")

    n8n = Broken(busy=0)

    with pytest.raises(RuntimeError, match="not found"):
        run_cli(n8n, "n8n publish:workflow --id=wf1", pause=0)
    assert len(n8n.commands) == 1


def test_export_refuses_workflow_with_secret_value():
    exported = {
        "id": "wf1", "name": "Demo", "active": False, "settings": {}, "connections": {},
        "nodes": [{"parameters": {"url": "https://api.telegram.org/botreal-token/sendMessage"}}],
    }

    with pytest.raises(SecretLeak, match="TELEGRAM_BOT_TOKEN"):
        repo_workflow(exported, secrets={"TELEGRAM_BOT_TOKEN": "real-token", "META_APP_SECRET": ""})


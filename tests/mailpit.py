"""Письма, которые n8n стенда отправил по SMTP: Mailpit (docker-compose.test.yml) принимает их
и показывает через свой REST API."""

from dataclasses import dataclass

import httpx


@dataclass
class Mail:
    sender: str
    to: list[str]
    subject: str
    text: str


class Mailpit:
    def __init__(self, url: str):
        self.http = httpx.Client(base_url=f"{url}/api/v1", timeout=10)

    def clear(self) -> None:
        self.http.delete("messages").raise_for_status()

    def messages(self) -> list[Mail]:
        """Все принятые письма, от старых к новым."""
        summaries = self.http.get("messages").raise_for_status().json()["messages"]
        return [self._read(summary["ID"]) for summary in reversed(summaries)]

    def _read(self, message_id: str) -> Mail:
        message = self.http.get(f"message/{message_id}").raise_for_status().json()
        return Mail(
            sender=message["From"]["Address"],
            to=[address["Address"] for address in message["To"]],
            subject=message["Subject"],
            text=message["Text"],
        )

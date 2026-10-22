"""Настоящая EspoCRM стенда в тестах: адрес, клиенты REST администратора и API-пользователя n8n."""

from dataclasses import dataclass

from scripts.espocrm import EspoCrm

# Учётка администратора из docker-compose.test.yml.
ESPOCRM_ADMIN = ("admin", "test-espocrm-admin")


@dataclass
class EspoCrmStand:
    url: str
    # Клиент администратора: настройки, пользователи, роли.
    admin: EspoCrm
    # Клиент API-пользователя n8n (X-Api-Key): с этими правами работают workflow.
    api: EspoCrm
    # host:port сервера WebSocket.
    websocket: str

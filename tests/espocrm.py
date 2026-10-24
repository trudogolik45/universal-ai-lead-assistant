"""Настоящая EspoCRM стенда в тестах: адрес, клиенты REST администратора и API-пользователя n8n."""

from dataclasses import dataclass

from scripts.espocrm import EspoCrm

# Учётка администратора из docker-compose.test.yml.
ESPOCRM_ADMIN = ("admin", "test-espocrm-admin")
# Куда хук EspoCRM шлёт Сообщение сотрудника: в контрактных тестах — фейк-сервер вместо n8n.
EMPLOYEE_REPLY_PATH = "/n8n/webhook/employee-reply"
# Куда хук EspoCRM шлёт закрытую Задачу человеку.
TASK_DONE_PATH = "/n8n/webhook/task-done"
# Куда хук EspoCRM шлёт смену статуса Заказ-наряда.
REPAIR_STATUS_PATH = "/n8n/webhook/repair-status"
# Куда хук EspoCRM шлёт смену статуса Сметы.
ESTIMATE_PATH = "/n8n/webhook/estimate"
# Секрет вебхуков хуков из docker-compose.test.yml: его же ждёт n8n.
N8N_HOOK_SECRET = "test-n8n-hook-secret"


@dataclass
class EspoCrmStand:
    url: str
    # Клиент администратора: настройки, пользователи, роли.
    admin: EspoCrm
    # Клиент API-пользователя n8n (X-Api-Key): с этими правами работают workflow.
    api: EspoCrm
    # host:port сервера WebSocket.
    websocket: str

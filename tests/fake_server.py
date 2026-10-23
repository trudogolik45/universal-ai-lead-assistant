"""Фейк внешних API (OpenRouter, Meta Graph, Telegram, EspoCRM) на хосте.

Один HTTP-сервер, у каждого API свой префикс пути: /openrouter, /meta, /telegram,
/espocrm (REST API EspoCRM), /n8n (вебхуки, которые хуки EspoCRM шлют n8n).
n8n ходит сюда по базовым URL из env (`*_BASE_URL`), см. `FakeServer.base_urls`.

Тест задаёт ответы через `respond` и читает полученные запросы через `requests`.
API с состоянием (EspoCRM, tests/fake_espocrm.py) подключается через `mount`: отвечает на всё под
своим префиксом, а `respond` на точный путь главнее него.
Незаданный маршрут отвечает 200 и `{}`: записывающим API (Send API, Telegram) этого хватает.
"""

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Имя env-переменной n8n → префикс пути фейка.
BASE_URL_ENV = {
    "OPENROUTER_BASE_URL": "/openrouter",
    "META_GRAPH_BASE_URL": "/meta",
    "TELEGRAM_API_BASE_URL": "/telegram",
    "ESPOCRM_BASE_URL": "/espocrm",
    "SMSAPI_BASE_URL": "/smsapi",
}

# Хост фейка, каким его видит n8n из контейнера.
CONTAINER_HOST = "host.docker.internal"
# Сколько фейк ждёт, пока клиент закроет соединение после ответа.
CLIENT_CLOSE_TIMEOUT = 60


@dataclass
class Request:
    method: str
    path: str
    headers: dict
    body: bytes

    def json(self):
        return json.loads(self.body)


@dataclass
class Response:
    status: int = 200
    body: object = field(default_factory=dict)


class FakeServer:
    def __init__(self):
        self._lock = threading.Lock()
        self._routes: dict[tuple[str, str], list[Response]] = {}
        self._mounts: dict[str, Callable[[Request], Response]] = {}
        self._requests: list[Request] = []
        self._httpd = ThreadingHTTPServer(("0.0.0.0", 0), self._handler_class())
        self.port = self._httpd.server_address[1]

    def start(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()

    def reset(self):
        with self._lock:
            self._routes.clear()
            self._requests.clear()
        for app in self._mounts.values():
            app.reset()

    def mount(self, path_prefix: str, app: Callable[[Request], Response]):
        """Фейк с состоянием под префиксом пути: app(request) → Response, app.reset() на сброс фейка."""
        self._mounts[path_prefix] = app

    def respond(self, method: str, path: str, *responses: Response):
        """Ответы на запросы по пути: по очереди, последний повторяется."""
        with self._lock:
            self._routes[(method.upper(), path)] = list(responses)

    def requests(self, path_prefix: str = "/") -> list[Request]:
        with self._lock:
            return [r for r in self._requests if r.path.startswith(path_prefix)]

    def container_url(self, path: str = "") -> str:
        """URL фейка для контейнеров стенда (например, адрес вебхука для хука EspoCRM)."""
        return f"http://{CONTAINER_HOST}:{self.port}{path}"

    def base_urls(self) -> dict[str, str]:
        return {env: self.container_url(prefix) for env, prefix in BASE_URL_ENV.items()}

    def _handle(self, request: Request) -> Response:
        with self._lock:
            self._requests.append(request)
            queue = self._routes.get((request.method, request.path.split("?")[0]))
            if queue:
                return queue.pop(0) if len(queue) > 1 else queue[0]
        app = next((app for prefix, app in self._mounts.items() if request.path.startswith(prefix)), None)
        return app(request) if app else Response()

    def _handler_class(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            # Соединение закрывает клиент: закрывший первым держит TIME_WAIT. Закрой первым фейк,
            # TIME_WAIT достанется сети Docker Desktop, а ядро контейнера n8n снова возьмёт тот же
            # порт к фейку — SYN теряется ~30 с, запрос опаздывает в следующий тест после сброса фейка.
            protocol_version = "HTTP/1.1"

            def handle(self):
                super().handle()
                self._wait_client_close()

            def _wait_client_close(self):
                self.connection.settimeout(CLIENT_CLOSE_TIMEOUT)
                try:
                    while self.connection.recv(4096):
                        pass
                except OSError:
                    pass

            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                request = Request(self.command, self.path, dict(self.headers), self.rfile.read(length))
                response = server._handle(request)
                payload = json.dumps(response.body).encode()
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

            def log_message(self, *args):
                pass

        return Handler

"""Фейк внешних API: соединение закрывает клиент (n8n), а не фейк.

Закрывший первым держит TIME_WAIT. Если это фейк, то TIME_WAIT держит сеть Docker Desktop,
а ядро контейнера n8n про него не знает и снова берёт тот же порт к фейку: SYN молча
теряется ~30 с, запрос опаздывает в следующий тест после сброса фейка.
"""

import socket

import pytest

from tests.fake_server import FakeServer

REQUEST = b"POST /crm/hook HTTP/1.1\r\nHost: fake\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"


@pytest.fixture
def server():
    server = FakeServer().start()
    yield server
    server.stop()


def read_response(sock: socket.socket) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        data += sock.recv(4096)
    head, body = data.split(b"\r\n\r\n", 1)
    length = int(next(line.split(b":")[1] for line in head.split(b"\r\n") if line.lower().startswith(b"content-length")))
    while len(body) < length:
        body += sock.recv(4096)
    return head


def test_fake_leaves_closing_connection_to_client(server):
    with socket.create_connection(("127.0.0.1", server.port)) as sock:
        sock.sendall(REQUEST)
        head = read_response(sock)
        sock.settimeout(0.5)

        with pytest.raises(TimeoutError):
            sock.recv(1)

    assert head.startswith(b"HTTP/1.1 200")

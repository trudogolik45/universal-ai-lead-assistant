"""Ожидание результата асинхронной обработки: вебхук отвечает 200 до записи в базу."""

import time


def eventually(probe, timeout: float = 10, interval: float = 0.2):
    """Ждёт, пока probe() вернёт истину, и возвращает это значение."""
    deadline = time.monotonic() + timeout
    while not (value := probe()) and time.monotonic() < deadline:
        time.sleep(interval)
    assert value, f"не дождались за {timeout} с"
    return value


def stays(probe, seconds: float = 2, interval: float = 0.2):
    """Проверяет, что probe() истинно всё окно: обработка, которой быть не должно, не случилась."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        assert probe(), "условие нарушилось в окне ожидания"
        time.sleep(interval)

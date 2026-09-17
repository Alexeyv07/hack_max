"""Настройка логирования: цветной вывод в консоль и опциональный JSON."""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from typing import Final

from project.config import get_settings

# ANSI-стили (отключаются, если stdout не TTY)
_RESET: Final = "\033[0m"
_DIM: Final = "\033[2m"
_BOLD: Final = "\033[1m"
_LEVEL_COLORS: Final[dict[int, str]] = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[35m",  # magenta
}


class ConsoleFormatter(logging.Formatter):
    """Читаемый однострочный форматтер с опциональными ANSI-цветами."""

    def __init__(self, *, use_color: bool = True) -> None:
        super().__init__()
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"
        level = record.levelname.ljust(8)
        location = f"{record.name}:{record.funcName}:{record.lineno}"
        message = record.getMessage()

        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"

        if not self.use_color:
            return f"{ts} | {level} | {location} | {message}"

        color = _LEVEL_COLORS.get(record.levelno, "")
        return (
            f"{_DIM}{ts}{_RESET} | "
            f"{color}{_BOLD}{level}{_RESET} | "
            f"{_DIM}{location}{_RESET} | "
            f"{message}"
        )


class JsonFormatter(logging.Formatter):
    """Компактный JSON Lines для продакшена / агрегаторов логов."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "func": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_configured = False


def setup_logging(*, force: bool = False) -> None:
    """Один раз настроить корневой логгер по настройкам приложения."""
    global _configured
    if _configured and not force:
        return

    settings = get_settings()
    level = getattr(logging, settings.logging.level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    use_color = sys.stdout.isatty()
    if settings.logging.format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter(use_color=use_color))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Приглушаем шумные сторонние логгеры (даже при DEBUG корня).
    noisy_level = logging.WARNING
    for name in (
        "httpx",
        "httpcore",
        "httpcore.connection",
        "httpcore.http11",
        "urllib3",
        "asyncio",
        "hpack",
    ):
        logging.getLogger(name).setLevel(noisy_level)

    # SQL: echo=true включает engine INFO — при DEBUG приложения всё равно режем до WARNING,
    # иначе парсер заливает консоль каждым SELECT.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).debug(
        "Логирование настроено (env=%s, level=%s, format=%s)",
        settings.environment,
        settings.logging.level,
        settings.logging.format,
    )


def get_logger(name: str) -> logging.Logger:
    """Вернуть именованный логгер; при необходимости сначала настроить логирование."""
    setup_logging()
    return logging.getLogger(name)

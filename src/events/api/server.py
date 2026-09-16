"""Запуск FastAPI в том же процессе, что и бот (uvicorn Server)."""

from __future__ import annotations

import uvicorn

from events.api.app import create_app
from project.config import get_settings
from project.logging_setup import get_logger

logger = get_logger(__name__)


async def run_api_server() -> None:
    """Поднять HTTP API (не отдельный OS-процесс)."""
    settings = get_settings()
    app = create_app()
    config = uvicorn.Config(
        app,
        host=settings.api.host,
        port=settings.api.port,
        log_level=settings.logging.level.lower(),
        lifespan="on",
    )
    server = uvicorn.Server(config)
    logger.info("HTTP API слушает http://%s:%s", settings.api.host, settings.api.port)
    await server.serve()

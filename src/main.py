"""Точка входа: Max-бот и/или HTTP API в одном процессе."""

from __future__ import annotations

import asyncio
import sys

from events.api.server import run_api_server
from project.config import get_settings
from project.database import check_connection
from project.logging_setup import get_logger, setup_logging
from project.max import run_max_bot


async def run() -> None:
    setup_logging()
    log = get_logger(__name__)
    settings = get_settings()

    log.info(
        "Запуск %s (environment=%s, debug=%s, bot=%s, api=%s)",
        settings.app.name,
        settings.environment,
        settings.app.debug,
        settings.runtime.enable_bot,
        settings.runtime.enable_api,
    )

    if not settings.runtime.enable_bot and not settings.runtime.enable_api:
        log.error(
            "Нечего запускать: включите runtime.enable_bot и/или runtime.enable_api в конфиге"
        )
        sys.exit(1)

    check_connection()

    tasks: list[asyncio.Task[None]] = []

    # Чтобы временно отключить сервис — поставьте enable_* = false в conf/*.yaml
    # или закомментируйте соответствующий create_task ниже.
    if settings.runtime.enable_api:
        tasks.append(asyncio.create_task(run_api_server(), name="api"))
    if settings.runtime.enable_bot:
        tasks.append(asyncio.create_task(run_max_bot(), name="max-bot"))

    assert tasks
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for task, result in zip(tasks, results, strict=True):
        if isinstance(result, Exception):
            log.exception("Сервис %s упал: %s", task.get_name(), result)
            raise result


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

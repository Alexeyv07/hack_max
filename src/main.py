"""Точка входа: Max-бот и/или HTTP API в одном процессе."""

from __future__ import annotations

import asyncio
import contextlib
import sys

from events.api.server import run_api_server
from parse_news import run_news_parser
from project.config import get_settings
from project.database import check_connection
from project.logging_setup import get_logger, setup_logging
from project.max import run_max_bot


async def _run_supervised(name: str, factory) -> None:
    """Сервис в цикле: падение не роняет соседние задачи."""
    log = get_logger(__name__)
    backoff = 1.0
    while True:
        try:
            await factory()
            log.warning("Сервис %s завершился штатно — перезапуск через %.0fs", name, backoff)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Сервис %s упал — перезапуск через %.0fs", name, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60.0)


async def run() -> None:
    setup_logging()
    log = get_logger(__name__)
    settings = get_settings()

    log.info(
        "Запуск %s (environment=%s, debug=%s, bot=%s, api=%s, news_parser=%s)",
        settings.app.name,
        settings.environment,
        settings.app.debug,
        settings.runtime.enable_bot,
        settings.runtime.enable_api,
        settings.runtime.enable_news_parser,
    )

    if (
        not settings.runtime.enable_bot
        and not settings.runtime.enable_api
        and not settings.runtime.enable_news_parser
    ):
        log.error(
            "Нечего запускать: включите runtime.enable_bot, runtime.enable_api "
            "и/или runtime.enable_news_parser в конфиге"
        )
        sys.exit(1)

    check_connection()

    tasks: list[asyncio.Task[None]] = []

    if settings.runtime.enable_api:
        tasks.append(asyncio.create_task(_run_supervised("api", run_api_server), name="api"))
    if settings.runtime.enable_bot:
        tasks.append(asyncio.create_task(_run_supervised("max-bot", run_max_bot), name="max-bot"))
    if settings.runtime.enable_news_parser:
        tasks.append(
            asyncio.create_task(_run_supervised("news-parser", run_news_parser), name="news-parser")
        )

    assert tasks
    # return_exceptions: падение одного сервиса не отменяет остальные через gather.
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for task, result in zip(tasks, results, strict=True):
        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
            log.exception("Фоновая задача %s завершилась с ошибкой: %s", task.get_name(), result)


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()

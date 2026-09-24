"""Точка входа: Max-бот и/или HTTP API в одном процессе."""

from __future__ import annotations

import asyncio
import contextlib
import sys

from events.api.server import run_api_server
from notify import run_notify_worker
from parse_mc import run_mc_parser
from parse_news import run_news_parser
from project.config import get_settings
from project.database import check_connection
from project.logging_setup import get_logger, setup_logging
from project.max import run_max_bot

# Парсеры (ONNX/spaCy + StreetCatalog) стартуют после API/бота — иначе судья ждёт 20–30с.
_PARSER_START_DELAY_S = 20.0


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


async def _run_parser_deferred(name: str, factory, *, delay_s: float) -> None:
    """Дать API/боту подняться и отвечать, потом включать тяжёлый парсинг."""
    log = get_logger(__name__)
    if delay_s > 0:
        log.info("Парсер %s стартует через %.0fs (приоритет API/бота)", name, delay_s)
        await asyncio.sleep(delay_s)
    await _run_supervised(name, factory)


async def run() -> None:
    setup_logging()
    log = get_logger(__name__)
    settings = get_settings()

    log.info(
        "Запуск %s (environment=%s, debug=%s, bot=%s, api=%s, news_parser=%s, "
        "mc_parser=%s, notify=%s)",
        settings.app.name,
        settings.environment,
        settings.app.debug,
        settings.runtime.enable_bot,
        settings.runtime.enable_api,
        settings.runtime.enable_news_parser,
        settings.runtime.enable_mc_parser,
        settings.notify.enabled,
    )

    if (
        not settings.runtime.enable_bot
        and not settings.runtime.enable_api
        and not settings.runtime.enable_news_parser
        and not settings.runtime.enable_mc_parser
    ):
        log.error(
            "Нечего запускать: включите runtime.enable_bot, runtime.enable_api, "
            "runtime.enable_news_parser и/или runtime.enable_mc_parser в конфиге"
        )
        sys.exit(1)

    check_connection()

    tasks: list[asyncio.Task[None]] = []

    # Сначала интерактивные сервисы — судья хакатона не должен ждать bootstrap-парсеры.
    if settings.runtime.enable_api:
        tasks.append(asyncio.create_task(_run_supervised("api", run_api_server), name="api"))
    if settings.runtime.enable_bot:
        tasks.append(asyncio.create_task(_run_supervised("max-bot", run_max_bot), name="max-bot"))
    if settings.runtime.enable_news_parser:
        tasks.append(
            asyncio.create_task(
                _run_parser_deferred(
                    "news-parser",
                    run_news_parser,
                    delay_s=_PARSER_START_DELAY_S,
                ),
                name="news-parser",
            )
        )
    if settings.runtime.enable_mc_parser:
        tasks.append(
            asyncio.create_task(
                _run_parser_deferred(
                    "mc-parser",
                    run_mc_parser,
                    delay_s=_PARSER_START_DELAY_S,
                ),
                name="mc-parser",
            )
        )

    if settings.notify.enabled:
        if settings.runtime.enable_bot:
            tasks.append(
                asyncio.create_task(
                    _run_supervised("notify", run_notify_worker),
                    name="notify",
                )
            )
        else:
            log.warning("Notify включён, но runtime.enable_bot=false — worker не запущен")

    assert tasks
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for task, result in zip(tasks, results, strict=True):
        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
            log.exception("Фоновая задача %s завершилась с ошибкой: %s", task.get_name(), result)


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()

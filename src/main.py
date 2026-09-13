"""Точка входа бота: wiring, проверка БД, polling Max."""

from __future__ import annotations

import asyncio
import sys

from maxapi import Bot, Dispatcher

from auth.commands import register_auth_commands
from project.config import get_settings
from project.database import check_connection
from project.logging_setup import get_logger, setup_logging


async def run() -> None:
    setup_logging()
    log = get_logger(__name__)
    settings = get_settings()

    log.info(
        "Запуск %s (environment=%s, debug=%s)",
        settings.app.name,
        settings.environment,
        settings.app.debug,
    )

    if not settings.max.bot_token:
        log.error("MAX_BOT_TOKEN не задан — отказ в запуске")
        sys.exit(1)

    check_connection()

    bot = Bot(settings.max.bot_token)
    dp = Dispatcher()
    register_auth_commands(dp, bot)

    log.info("Polling Max-бота запущен")
    await dp.start_polling(bot)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

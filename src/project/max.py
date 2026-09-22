"""Запуск Max-бота (polling). Вызывается из main — можно отключить флагом runtime.enable_bot."""

from __future__ import annotations

from typing import Any

from maxapi import Bot, Dispatcher

from auth.commands import register_auth_commands
from chat_link.commands import register_chat_link_commands
from chat_link.handlers import get_address_catalog
from parse_chat import register_parse_chat_commands
from project.config import get_settings
from project.logging_setup import get_logger
from project.max_runtime import set_max_bot

logger = get_logger(__name__)


def _patch_get_updates_limit(bot: Bot, *, limit: int) -> None:
    """Ограничить батч Max get_updates — по одному событию на poll."""
    original = bot.get_updates

    async def get_updates_capped(
        limit_arg: int | None = None,
        timeout: int | None = None,
        marker: int | None = None,
        types: Any = None,
    ) -> dict:
        effective = limit if limit_arg is None else min(int(limit_arg), limit)
        return await original(
            limit=effective,
            timeout=timeout,
            marker=marker,
            types=types,
        )

    bot.get_updates = get_updates_capped  # type: ignore[method-assign]
    logger.info("Max get_updates limit=%s (inline chat/news latency)", limit)


async def run_max_bot() -> None:
    """Polling Max-бота. Токен обязателен только если бот реально запускают."""
    settings = get_settings()

    if not settings.max.bot_token:
        raise RuntimeError("MAX_BOT_TOKEN не задан — бот не может стартовать")

    bot = Bot(settings.max.bot_token)
    # Нужен для OpenAppButton (username / contact_id).
    try:
        bot.me = await bot.get_me()
        logger.info(
            "Max bot identity: id=%s username=%s",
            getattr(bot.me, "user_id", None),
            getattr(bot.me, "username", None),
        )
    except Exception:
        logger.exception("Не удалось получить GET /me — open_app возьмёт fallback из конфига")

    set_max_bot(bot)

    # KAN-7: адресный picker работает только по process-wide snapshot.
    # Прогреваем его до polling, чтобы первый callback не делал большой SELECT
    # и не строил индексы уже после нажатия пользователя.
    get_address_catalog()

    chat_on = settings.runtime.enable_chat_parser and settings.chat_parser.enabled
    if chat_on:
        _patch_get_updates_limit(bot, limit=settings.chat_parser.updates_limit)

    # use_create_task=False: события строго по одному (await handle), без параллельного батча.
    dp = Dispatcher(use_create_task=False)
    register_auth_commands(dp, bot)
    register_chat_link_commands(dp, bot)
    if chat_on:
        register_parse_chat_commands(dp, bot)
        logger.info(
            "parse_chat: inline 1-msg flow (updates_limit=%s, no queue/batch)",
            settings.chat_parser.updates_limit,
        )

    logger.info("Polling Max-бота запущен")
    await dp.start_polling(bot)

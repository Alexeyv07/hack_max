"""Запуск Max-бота (polling). Вызывается из main — можно отключить флагом runtime.enable_bot."""

from __future__ import annotations

import asyncio
from typing import Any

from maxapi import Bot, Dispatcher

from auth.commands import register_auth_commands
from chat_link.commands import register_chat_link_commands
from chat_link.handlers import get_address_catalog
from notify.commands import register_notify_commands
from parse_chat import register_parse_chat_commands
from project.config import get_settings
from project.logging_setup import get_logger
from project.max_runtime import set_max_bot

logger = get_logger(__name__)


def _patch_get_updates_limit(bot: Bot, *, limit: int) -> None:
    """Ограничить батч Max get_updates."""
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
    logger.info("Max get_updates limit=%s", limit)


def _warm_chat_ml() -> None:
    """Прогреть classify + time + dedup ONNX до первого сообщения."""
    sample = "прогрев: отключили воду во дворе с 10:00 до 18:00"
    try:
        from parser_common.classify import classify_importance

        classify_importance(sample)
        logger.info("warm ML: classify ok")
    except Exception:
        logger.debug("warm classify skipped", exc_info=True)
    try:
        from parser_common.time_extract import extract_active_window

        extract_active_window(sample, use_model=True)
        logger.info("warm ML: time ok")
    except Exception:
        logger.debug("warm time skipped", exc_info=True)
    try:
        from ml_dedup.embed import embed_text

        embed_text(sample, allow_hash_fallback=True)
        logger.info("warm ML: dedup embed ok")
    except Exception:
        logger.debug("warm embed skipped", exc_info=True)


async def run_max_bot() -> None:
    """Polling Max-бота. Токен обязателен только если бот реально запускают."""
    settings = get_settings()

    if not settings.max.bot_token:
        raise RuntimeError("MAX_BOT_TOKEN не задан — бот не может стартовать")

    bot = Bot(settings.max.bot_token)
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
    get_address_catalog()

    chat_on = settings.runtime.enable_chat_parser and settings.chat_parser.enabled
    if chat_on:
        _patch_get_updates_limit(bot, limit=settings.chat_parser.updates_limit)
        # Прогрев в фоне — не блокируем старт polling.
        asyncio.create_task(asyncio.to_thread(_warm_chat_ml), name="warm-chat-ml")

    # True: handlers не сериализуют polling. parse_chat сам fire-and-forget.
    dp = Dispatcher(use_create_task=True)
    register_auth_commands(dp, bot)
    # notify имеет фильтр по payload, а chat_link ниже ловит любой callback.
    # В MAX API выполняется первый подходящий handler, поэтому notify должен быть раньше.
    register_notify_commands(dp, bot)
    register_chat_link_commands(dp, bot)
    if chat_on or settings.notify.enabled:
        # Один message_created listener: digest собирает обычные тексты, KAN-10 — events.
        register_parse_chat_commands(dp, bot)
        logger.info(
            "chat listener: parse_chat=%s digest_capture=%s",
            chat_on,
            settings.notify.enabled,
        )

    logger.info("Polling Max-бота запущен")
    await dp.start_polling(bot)

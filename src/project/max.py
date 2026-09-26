"""Запуск Max-бота (polling). Вызывается из main — можно отключить флагом runtime.enable_bot."""

from __future__ import annotations

import asyncio
from typing import Any

from maxapi import Bot, Dispatcher

from auth.commands import publish_bot_commands, register_auth_commands
from chat_link.commands import register_chat_link_commands
from chat_link.handlers import get_address_catalog
from notify.commands import register_notify_commands
from parse_chat import register_parse_chat_commands
from project.bot_media import install_bot_images, warm_bot_images
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

    install_bot_images(bot)
    # Token'ы картинок один раз: иначе каждый экран ждёт upload ~0.5–2с.
    await warm_bot_images(bot)
    set_max_bot(bot)

    chat_on = settings.runtime.enable_chat_parser and settings.chat_parser.enabled
    if chat_on:
        _patch_get_updates_limit(bot, limit=settings.chat_parser.updates_limit)

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

    # Меню «/» в клиенте Max — отдельно от handlers; без PATCH команды не видны.
    try:
        await publish_bot_commands(bot)
    except Exception:
        logger.exception("Не удалось опубликовать команды бота в Max (PATCH /me/commands)")

    # ~125k адресов: греем в фоне после регистрации хендлеров, чтобы polling
    # стартовал сразу. Первый выбор адреса дождётся готовности каталога.
    catalog_ready = asyncio.create_task(
        asyncio.to_thread(get_address_catalog),
        name="address-catalog-warm",
    )

    def _catalog_done(task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.exception("Не удалось прогреть StreetCatalog", exc_info=exc)
        else:
            logger.info("StreetCatalog готов")

    catalog_ready.add_done_callback(_catalog_done)

    logger.info("Polling Max-бота запущен (каталог адресов греется в фоне)")
    await dp.start_polling(bot)

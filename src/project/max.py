"""Запуск Max-бота (polling). Вызывается из main — можно отключить флагом runtime.enable_bot."""

from __future__ import annotations

from maxapi import Bot, Dispatcher

from auth.commands import register_auth_commands
from chat_link.commands import register_chat_link_commands
from chat_link.handlers import get_address_catalog
from notify.commands import register_notify_commands
from project.config import get_settings
from project.logging_setup import get_logger
from project.max_runtime import set_max_bot

logger = get_logger(__name__)


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

    dp = Dispatcher()
    register_auth_commands(dp, bot)
    register_chat_link_commands(dp, bot)
    register_notify_commands(dp)

    logger.info("Polling Max-бота запущен")
    await dp.start_polling(bot)

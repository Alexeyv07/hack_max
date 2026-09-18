"""Запуск Max-бота (polling). Вызывается из main — можно отключить флагом runtime.enable_bot."""

from __future__ import annotations

from maxapi import Bot, Dispatcher

from auth.commands import register_auth_commands
from project.config import get_settings
from project.logging_setup import get_logger

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

    dp = Dispatcher()
    register_auth_commands(dp, bot)

    logger.info("Polling Max-бота запущен")
    await dp.start_polling(bot)

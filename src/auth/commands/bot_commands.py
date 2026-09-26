"""Публикация slash-команд бота в меню Max (PATCH /me/commands)."""

from __future__ import annotations

from typing import Any

from maxapi.connection.base import BaseConnection
from maxapi.enums.http_method import HTTPMethod
from maxapi.types import BotCommand

from project.logging_setup import get_logger

logger = get_logger(__name__)

# Подсказки при вводе «/» в клиенте Max (до 32 шт.).
BOT_MENU_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand(name="home", description="Главная: адреса и новости рядом"),
    BotCommand(name="get_notify", description="Пример уведомления о событии"),
    BotCommand(name="address", description="Адреса этого группового чата"),
)


class _SetMeCommands(BaseConnection):
    """Официальный PATCH /me/commands (в maxapi 1.2 ещё нет обёртки)."""

    def __init__(self, bot: Any, commands: list[BotCommand]) -> None:
        super().__init__()
        self.bot = bot
        self.commands = commands

    async def fetch(self) -> dict[str, Any]:
        bot = self._ensure_bot()
        raw = await super().request(
            method=HTTPMethod.PATCH,
            path="/me/commands",
            is_return_raw=True,
            params=bot.params,
            json={"commands": [command.model_dump(exclude_none=True) for command in self.commands]},
        )
        return raw if isinstance(raw, dict) else {}


async def publish_bot_commands(bot: Any) -> list[str]:
    """Заменить список команд бота в Max на актуальный.

    Returns:
        Имена успешно опубликованных команд (из ответа API или из запроса).
    """
    result = await _SetMeCommands(bot, list(BOT_MENU_COMMANDS)).fetch()
    published = result.get("commands")
    if isinstance(published, list) and published:
        names = [
            str(item.get("name"))
            for item in published
            if isinstance(item, dict) and item.get("name")
        ]
    else:
        names = [command.name for command in BOT_MENU_COMMANDS]
    logger.info("Команды бота в Max: %s", ", ".join(f"/{name}" for name in names))
    return names

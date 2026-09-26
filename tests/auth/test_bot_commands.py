"""Публикация slash-команд бота в Max."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from auth.commands.bot_commands import BOT_MENU_COMMANDS, publish_bot_commands


def test_publish_bot_commands_patches_me_commands(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeSetMeCommands:
        def __init__(self, bot: object, commands: list[object]) -> None:
            captured["bot"] = bot
            captured["commands"] = commands

        async def fetch(self) -> dict[str, object]:
            return {
                "commands": [
                    {"name": "home", "description": "Главная: адреса и новости рядом"},
                    {"name": "get_notify", "description": "Пример уведомления о событии"},
                    {"name": "address", "description": "Адреса этого группового чата"},
                ]
            }

    monkeypatch.setattr("auth.commands.bot_commands._SetMeCommands", FakeSetMeCommands)

    bot = SimpleNamespace()
    names = asyncio.run(publish_bot_commands(bot))

    assert names == ["home", "get_notify", "address"]
    assert captured["bot"] is bot
    published = captured["commands"]
    assert isinstance(published, list)
    assert [command.name for command in published] == [c.name for c in BOT_MENU_COMMANDS]
    assert all(command.description for command in published)


def test_bot_menu_commands_cover_handlers() -> None:
    names = {command.name for command in BOT_MENU_COMMANDS}
    assert names == {"home", "get_notify", "address"}
    assert all(1 <= len(command.name) <= 64 for command in BOT_MENU_COMMANDS)
    assert all(
        command.description and 1 <= len(command.description) <= 128
        for command in BOT_MENU_COMMANDS
    )

"""Очистка касается только навигации, а не уведомлений или пользовательского ввода."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from project.bot_screens import remember_screen, send_screen


def _result(mid: str):
    return SimpleNamespace(message=SimpleNamespace(body=SimpleNamespace(mid=mid)))


def test_new_screen_deletes_previous_only_after_success() -> None:
    bot = SimpleNamespace(
        send_message=AsyncMock(side_effect=[_result("screen-1"), _result("screen-2")]),
        delete_message=AsyncMock(),
    )

    async def scenario():
        await send_screen(bot, 42, user_id=42, text="Первый экран")
        await send_screen(bot, 42, user_id=42, text="Второй экран")

    asyncio.run(scenario())
    bot.delete_message.assert_awaited_once_with("screen-1")
    assert bot._ui_screen_mids[42] == "screen-2"


def test_send_failure_keeps_old_screen() -> None:
    bot = SimpleNamespace(
        send_message=AsyncMock(side_effect=[_result("screen-1"), RuntimeError("network")]),
        delete_message=AsyncMock(),
    )

    async def scenario():
        await send_screen(bot, 42, user_id=42, text="Первый")
        with pytest.raises(RuntimeError):
            await send_screen(bot, 42, user_id=42, text="Новый")

    asyncio.run(scenario())
    bot.delete_message.assert_not_awaited()
    assert bot._ui_screen_mids[42] == "screen-1"


def test_same_window_remains_and_other_users_not_affected() -> None:
    bot = SimpleNamespace(send_message=AsyncMock(), delete_message=AsyncMock())

    async def scenario():
        await remember_screen(bot, 42, "screen-1")
        await remember_screen(bot, 42, "screen-1")
        await remember_screen(bot, 43, "another-user-screen")

    asyncio.run(scenario())
    bot.delete_message.assert_not_awaited()


def test_notify_message_is_not_registered_or_deleted() -> None:
    bot = SimpleNamespace(
        send_message=AsyncMock(side_effect=[_result("ui-1"), _result("notify"), _result("ui-2")]),
        delete_message=AsyncMock(),
    )

    async def scenario():
        await send_screen(bot, 42, user_id=42, text="Меню")
        await bot.send_message(user_id=42, text="🔴 Уведомление")
        await send_screen(bot, 42, user_id=42, text="Адреса")

    asyncio.run(scenario())
    bot.delete_message.assert_awaited_once_with("ui-1")
    assert bot._ui_screen_mids[42] == "ui-2"


def test_no_mid_does_not_delete_old_screen() -> None:
    bot = SimpleNamespace(send_message=AsyncMock(return_value=None), delete_message=AsyncMock())

    async def scenario():
        await remember_screen(bot, 42, "ui-1")
        await send_screen(bot, 42, previous_mid="ui-1", user_id=42, text="Новый")

    asyncio.run(scenario())
    bot.delete_message.assert_not_awaited()
    assert bot._ui_screen_mids[42] == "ui-1"

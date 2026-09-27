"""Одно актуальное навигационное сообщение в личке MAX.

Вызывать только для экранов меню/онбординга: уведомления и события не являются
экранами и не должны передаваться сюда. Старый экран удаляется ПОСЛЕ успешной
отправки нового; при ошибке отправки пользователь не теряет рабочие кнопки.
"""

from __future__ import annotations

import asyncio
from typing import Any

from project.logging_setup import get_logger

logger = get_logger(__name__)


def sent_mid(result: Any) -> str | None:
    mid = getattr(getattr(getattr(result, "message", None), "body", None), "mid", None)
    return str(mid) if isinstance(mid, (str, int)) and mid else None


def _state(bot: Any) -> tuple[dict[int, str], dict[int, asyncio.Lock]]:
    screens = getattr(bot, "_ui_screen_mids", None)
    locks = getattr(bot, "_ui_screen_locks", None)
    if not isinstance(screens, dict):
        screens = {}
        bot._ui_screen_mids = screens
    if not isinstance(locks, dict):
        locks = {}
        bot._ui_screen_locks = locks
    return screens, locks


async def _delete_old(bot: Any, user_id: int, old: str | None, current: str) -> None:
    if not old or old == current:
        return
    delete = getattr(bot, "delete_message", None)
    if not callable(delete):
        return
    try:
        await delete(str(old))
    except Exception:
        # MAX может запретить удаление (например, слишком старого сообщения).
        # Новый экран в таком случае остаётся рабочим.
        logger.debug(
            "Не удалось удалить старый экран user_id=%s mid=%s", user_id, old, exc_info=True
        )


async def send_screen(
    bot: Any,
    screen_owner_id: int,
    *,
    previous_mid: str | None = None,
    **kwargs: Any,
) -> Any:
    """Отправить новый экран внизу переписки, только потом убрать предыдущий."""
    screens, locks = _state(bot)
    async with locks.setdefault(screen_owner_id, asyncio.Lock()):
        old = screens.get(screen_owner_id)
        result = await bot.send_message(**kwargs)
        mid = sent_mid(result)
        if mid is None:
            return result  # Не удаляем старый экран, если новый mid неизвестен.
        screens[screen_owner_id] = mid
        await _delete_old(bot, screen_owner_id, old, mid)
        if previous_mid != old:
            await _delete_old(bot, screen_owner_id, previous_mid, mid)
        return result


async def remember_screen(
    bot: Any, screen_owner_id: int, mid: str | None, *, previous_mid: str | None = None
) -> None:
    """Учесть успешно созданный/отредактированный экран (в т.ч. callback)."""
    if not mid:
        return
    screens, locks = _state(bot)
    async with locks.setdefault(screen_owner_id, asyncio.Lock()):
        old = screens.get(screen_owner_id)
        screens[screen_owner_id] = str(mid)
        await _delete_old(bot, screen_owner_id, old, str(mid))
        if previous_mid != old:
            await _delete_old(bot, screen_owner_id, previous_mid, str(mid))

"""Список MAX-групп бота; права проверяем только по живому ответу MAX."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maxapi.enums import ChatType
from maxapi.exceptions.max import MaxApiError
from sqlalchemy import select
from sqlalchemy.orm import Session

from chat_link.db import BotGroupRow
from chat_link.handlers.group import bot_can_read_group


@dataclass(frozen=True, slots=True)
class AdminGroup:
    chat_id: int
    title: str


def register_bot_group(
    session: Session, chat_id: int, *, actor_max_user_id: int | None, title: str | None = None
) -> None:
    """bot_added: сохраняем группу даже при отсутствии адреса/заявки."""
    row = session.get(BotGroupRow, chat_id)
    if row is None:
        session.add(
            BotGroupRow(
                chat_id=chat_id,
                title=(title or f"Чат {chat_id}")[:255],
                added_by_user_id=actor_max_user_id,
                is_active=True,
            )
        )
        session.flush()
        return
    row.is_active = True
    row.added_by_user_id = actor_max_user_id
    if title:
        row.title = title[:255]


def deactivate_bot_group(session: Session, chat_id: int) -> None:
    """bot_removed: удаление бота из группы делает её недоступной для привязок."""
    row = session.get(BotGroupRow, chat_id)
    if row is not None:
        row.is_active = False


async def eligible_admin_group(
    bot: Any, session: Session, *, chat_id: int, max_user_id: int
) -> AdminGroup | None:
    """Повторная проверка одного чата перед выбором и подтверждением.

    Отсутствие прав -> None, сбой MAX -> исключение (не притворяемся, что групп нет).
    """
    row = session.get(BotGroupRow, chat_id)
    if row is None or not row.is_active:
        return None
    try:
        remote = await bot.get_chat_by_id(chat_id)
    except MaxApiError as exc:
        if exc.code in {400, 403, 404}:
            return None
        raise
    if getattr(remote, "type", None) != ChatType.CHAT:
        return None
    try:
        if not await bot_can_read_group(bot, chat_id):
            return None
        member = await bot.get_chat_member(chat_id, max_user_id)
    except MaxApiError as exc:
        if exc.code in {400, 403, 404}:
            return None
        raise
    if member is None or not (
        getattr(member, "is_admin", False) or getattr(member, "is_owner", False)
    ):
        return None
    title = getattr(remote, "title", None) or row.title
    if title != row.title:
        row.title = title[:255]
    return AdminGroup(chat_id=chat_id, title=title)


async def eligible_admin_groups(
    bot: Any, session: Session, *, max_user_id: int
) -> list[AdminGroup]:
    """Включает и не привязанные группы; сортировка только для стабильного UI."""
    ids = session.scalars(
        select(BotGroupRow.chat_id)
        .where(BotGroupRow.is_active.is_(True))
        .order_by(BotGroupRow.chat_id)
    ).all()
    groups: list[AdminGroup] = []
    for chat_id in ids:
        candidate = await eligible_admin_group(
            bot, session, chat_id=chat_id, max_user_id=max_user_id
        )
        if candidate is not None:
            groups.append(candidate)
    return sorted(groups, key=lambda group: (group.title.casefold(), group.chat_id))

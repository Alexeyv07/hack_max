"""Результат выбора дома: подтверждение членства, приглашение или настройка группы."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from auth.handlers.residence import set_personal_address
from chat_link.handlers.links import create_request
from user_chat.handlers import list_chats_by_address, remove_user_from_chat, set_member_address
from user_chat.handlers.membership import bind_known_chat_member


@dataclass(frozen=True, slots=True)
class ResidenceSelection:
    mode: Literal["personal_address", "not_member", "no_chat"]
    token: str | None = None


async def resolve_residence(
    bot: object, session: Session, *, max_user_id: int, address_id: int
) -> ResidenceSelection:
    """Проверить выбранный адрес, не выдавая доступ по одному лишь адресу.

    Проверяем MAX, а не только старую запись users_chat. При сетевой ошибке
    исключение пробрасывается: отсутствие ответа не равно отсутствию членства.
    """
    chats = list_chats_by_address(session, address_id)
    for chat in chats:
        member = await bot.get_chat_member(chat.chat_id, max_user_id)
        if member is None:
            # На случай пропущенного user_removed: устаревшее локальное членство
            # не должно сохранять доступ к nearby после отказа MAX.
            remove_user_from_chat(session, chat.chat_id, max_user_id=max_user_id)
            continue
        bind_known_chat_member(session, chat.chat_id, max_user_id=max_user_id)
        set_member_address(session, chat.chat_id, max_user_id=max_user_id, address_id=address_id)
        set_personal_address(session, max_user_id=max_user_id, address_id=address_id)
        return ResidenceSelection("personal_address")
    if chats:
        return ResidenceSelection("not_member")
    request, _ = create_request(session, max_user_id=max_user_id, address_id=address_id)
    return ResidenceSelection("no_chat", token=request.token)

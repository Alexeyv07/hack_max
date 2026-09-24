"""Главный экран после выбора адреса в боте или WebApp."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from maxapi.enums.format import Format
from maxapi.types import CallbackButton, InputMedia, LinkButton, OpenAppButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from auth.db.user import UserRow
from auth.handlers.residence import get_personal_address
from project.config import get_settings
from project.logging_setup import get_logger
from user_chat.db import ChatRow, users_chat
from user_chat.handlers.membership import has_linked_group, linked_group_ids

logger = get_logger(__name__)
MANAGE_ADDRESSES_PAYLOAD = "home:manage"
HOME_IMAGE_PATH = Path(__file__).resolve().parents[1] / "assets" / "home.jpg"


def linked_addresses(session: Session, max_user_id: int) -> list[str]:
    """Личный адрес плюс фактически выбранные дома из чатов (без повторов)."""
    if not has_linked_group(session, max_user_id):
        return []
    personal = get_personal_address(session, max_user_id)
    if personal and not linked_group_ids(session, max_user_id, address_id=personal.id):
        personal = None
    rows = session.scalars(
        select(AddressRow.address_text)
        .join(users_chat, users_chat.c.address_id == AddressRow.id)
        .join(UserRow, UserRow.id == users_chat.c.user_id)
        .join(ChatRow, ChatRow.chat_id == users_chat.c.chat_id)
        .where(UserRow.max_user_id == max_user_id, ChatRow.chat_type == "chat")
        .distinct()
        .order_by(AddressRow.address_text)
    )
    return list(dict.fromkeys(([personal.address_text] if personal else []) + list(rows)))


def build_home_text(addresses: list[str], *, notice: str | None = None) -> str:
    """Строка '-' означает, что адрес ещё не привязан, а не потерян при рендеринге."""
    if addresses:
        lines = [f"• {escape(address)}" for address in addresses[:12]]
        if len(addresses) > 12:
            lines.append(f"…и ещё {len(addresses) - 12}")
        address_block = "\n".join(lines)
    else:
        address_block = "—"
    text = (
        f"<b>Ваши адреса 🏠</b>\n\n{address_block}\n\n"
        "Смотрите, что происходит рядом с вашими домами и в городе: "
        "отключения воды, ремонт, перекрытия и другие события.\n\n"
        "Нажмите кнопку ниже, чтобы открыть новости 🕊"
    )
    if notice:
        text += f"\n\n{escape(notice)}"
    return text


def build_home_keyboard(bot: Any) -> Any:
    me = getattr(bot, "me", None)
    builder = InlineKeyboardBuilder()
    builder.row(
        OpenAppButton(
            text="Посмотреть новости рядом",
            web_app=getattr(me, "username", None),
            contact_id=getattr(me, "user_id", None),
        )
    )
    builder.row(CallbackButton(text="Управлять адресами", payload=MANAGE_ADDRESSES_PAYLOAD))
    builder.row(LinkButton(text="Помощь и обратная связь", url=get_settings().docs.url))
    return builder.as_markup()


async def send_home(
    bot: Any,
    session: Session,
    max_user_id: int,
    *,
    notice: str | None = None,
    recipient_chat_id: int | None = None,
) -> Any:
    """Новое сообщение: фото, реальные привязанные дома и кнопки одним отправлением."""
    user = session.scalar(select(UserRow).where(UserRow.max_user_id == max_user_id))
    if user is None:
        raise ValueError("Пользователь не найден")
    chat_id = recipient_chat_id or user.chat_id
    recipient = (
        {"chat_id": chat_id} if chat_id is not None and chat_id > 0 else {"user_id": max_user_id}
    )
    text = build_home_text(linked_addresses(session, max_user_id), notice=notice)
    keyboard = build_home_keyboard(bot)
    try:
        return await bot.send_message(
            **recipient,
            text=text,
            attachments=[InputMedia(str(HOME_IMAGE_PATH), type="image"), keyboard],
            format=Format.HTML,
        )
    except Exception:
        # Ошибка медиа не должна оставлять пользователя без кнопок навигации.
        logger.exception("Не удалось отправить главную с изображением; отправляем текстовую версию")
        return await bot.send_message(
            **recipient,
            text=text,
            attachments=[keyboard],
            format=Format.HTML,
        )

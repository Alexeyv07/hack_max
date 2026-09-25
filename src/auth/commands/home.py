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

from auth.db.user import UserRow
from auth.handlers.managed_addresses import list_managed_addresses
from project.config import get_settings
from project.logging_setup import get_logger

logger = get_logger(__name__)
MANAGE_ADDRESSES_PAYLOAD = "home:manage"
HOME_IMAGE_PATH = Path(__file__).resolve().parents[1] / "assets" / "home.jpg"


def linked_addresses(session: Session, max_user_id: int) -> list[str]:
    """Выбранные пользователем адреса, а не все дома его групп."""
    return [address.text for address in list_managed_addresses(session, max_user_id)]


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

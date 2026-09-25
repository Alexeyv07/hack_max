"""Главный экран после выбора адреса в боте или WebApp."""

from __future__ import annotations

from html import escape
from typing import Any

from maxapi.enums.format import Format
from maxapi.types import CallbackButton, OpenAppButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.db.user import UserRow
from auth.handlers.managed_addresses import list_managed_addresses
from project.bot_media import HOME_IMAGE_PATH, home_image
from project.docs_links import docs_html
from project.logging_setup import get_logger

logger = get_logger(__name__)
MANAGE_ADDRESSES_PAYLOAD = "home:manage"


def linked_addresses(session: Session, max_user_id: int) -> list[str]:
    """Выбранные пользователем адреса, а не все дома его групп."""
    return [address.text for address in list_managed_addresses(session, max_user_id)]


def build_home_text(addresses: list[str], *, notice: str | None = None) -> str:
    """Главная после онбординга: дома пользователя и следующий шаг — новости."""
    if addresses:
        lines = [f"• {escape(address)}" for address in addresses[:12]]
        if len(addresses) > 12:
            lines.append(f"…и ещё {len(addresses) - 12}")
        address_block = "\n".join(lines)
    else:
        address_block = "—"
    help_link = docs_html("справка о сервисе", page="overview")
    text = (
        "<b>Главная</b>\n\n"
        f"<b>Ваши адреса 🏠</b>\n{address_block}\n\n"
        "Здесь собрано то, что касается вашего дома и города: "
        "отключения воды, ремонт, перекрытия и другие события.\n\n"
        "Нажмите «Посмотреть новости рядом», чтобы открыть ленту. "
        f"Если нужно добавить или убрать дом — «Управлять адресами».\n\n"
        "Команды: /home — эта страница · /get_notify — получить тестовое оповещение \n\n"
        f"Документация: {help_link}"
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
            attachments=[home_image(bot), keyboard],
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


# Обратная совместимость для тестов, которые импортируют путь напрямую.
__all__ = [
    "HOME_IMAGE_PATH",
    "MANAGE_ADDRESSES_PAYLOAD",
    "build_home_keyboard",
    "build_home_text",
    "linked_addresses",
    "send_home",
]

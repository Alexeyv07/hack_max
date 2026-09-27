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
from chat_link.handlers.registry import connected_admin_groups
from project.bot_media import HOME_IMAGE_PATH, home_image
from project.docs_links import docs_html
from project.logging_setup import get_logger

logger = get_logger(__name__)
MANAGE_ADDRESSES_PAYLOAD = "home:manage"
MANAGE_CHATS_PAYLOAD = "home:chats"
HELP_PAYLOAD = "home:help"
CHAT_LINK_START_PAYLOAD = "chat_link:start"


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
        body = (
            "Здесь собрано то, что касается вашего дома и города: "
            "отключения воды, ремонт, перекрытия и другие события.\n\n"
            "Нажмите «Посмотреть новости рядом», чтобы открыть ленту. "
            "Личные адреса можно изменить в разделе «Мои адреса»."
        )
    else:
        address_block = "—"
        body = (
            "Пока нет сохранённого адреса — лента новостей рядом будет пустой.\n\n"
            "Нажмите «Мои адреса», чтобы добавить свой дом."
        )
    help_link = docs_html("О сервисе", page="overview")
    text = (
        "<b>Главная</b>\n\n"
        f"<b>Ваши адреса 🏠</b>\n{address_block}\n\n"
        f"{body}\n\n"
        "Команды: /home — эта страница · /get_notify — пример уведомления\n\n"
        f"{help_link}"
    )
    if notice:
        text += f"\n\n{escape(notice)}"
    return text


def build_home_keyboard(
    bot: Any, *, has_addresses: bool | None = None, has_admin_chats: bool = False
) -> Any:
    me = getattr(bot, "me", None)
    builder = InlineKeyboardBuilder()
    if has_addresses:
        builder.row(
            OpenAppButton(
                text="Посмотреть новости рядом",
                web_app=getattr(me, "username", None),
                contact_id=getattr(me, "user_id", None),
            )
        )
    builder.row(CallbackButton(text="Мои адреса", payload=MANAGE_ADDRESSES_PAYLOAD))
    if has_admin_chats:
        builder.row(CallbackButton(text="Управлять чатами", payload=MANAGE_CHATS_PAYLOAD))
    builder.row(CallbackButton(text="Помощь и обратная связь", payload=HELP_PAYLOAD))
    return builder.as_markup()


async def has_connected_admin_chats(bot: Any, session: Session, max_user_id: int) -> bool:
    """Кнопку видят только администраторы реально подключённых групп.

    При сбое MAX не делаем вывод, что права действуют: экран не должен давать
    обходить повторную проверку при действиях над чатом.
    """
    try:
        return bool(await connected_admin_groups(bot, session, max_user_id=max_user_id))
    except Exception:
        logger.exception("Не удалось проверить права для меню управления чатами")
        return False


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
    addresses = linked_addresses(session, max_user_id)
    text = build_home_text(addresses, notice=notice)
    has_admin_chats = await has_connected_admin_chats(bot, session, max_user_id)
    keyboard = build_home_keyboard(
        bot, has_addresses=bool(addresses), has_admin_chats=has_admin_chats
    )
    try:
        return await bot.send_message(
            **recipient,
            text=text,
            attachments=[home_image(bot), keyboard],
            format=Format.HTML,
        )
    except Exception:
        logger.exception("Не удалось отправить главную с изображением; отправляем текстовую версию")
        return await bot.send_message(
            **recipient,
            text=text,
            attachments=[keyboard],
            format=Format.HTML,
        )


async def edit_to_home(
    bot: Any,
    event: Any,
    session: Session,
    max_user_id: int,
    *,
    notice: str | None = None,
) -> bool:
    """Заменить текущий bot-screen на главную (без второго сообщения)."""
    addresses = linked_addresses(session, max_user_id)
    text = build_home_text(addresses, notice=notice)
    has_admin_chats = await has_connected_admin_chats(bot, session, max_user_id)
    attachments = [
        home_image(bot),
        build_home_keyboard(bot, has_addresses=bool(addresses), has_admin_chats=has_admin_chats),
    ]
    edit = getattr(event, "edit", None)
    if callable(edit):
        try:
            await edit(
                text=text,
                attachments=attachments,
                format=Format.HTML,
                notify=False,
                notification="Главная",
            )
            return True
        except Exception:
            logger.debug("event.edit → home не удался", exc_info=True)
    mid = getattr(getattr(getattr(event, "message", None), "body", None), "mid", None)
    if mid:
        try:
            await bot.edit_message(
                str(mid),
                text=text,
                attachments=attachments,
                format=Format.HTML,
                notify=False,
            )
            return True
        except Exception:
            logger.debug("edit_message → home не удался", exc_info=True)
    return False


__all__ = [
    "CHAT_LINK_START_PAYLOAD",
    "HOME_IMAGE_PATH",
    "MANAGE_ADDRESSES_PAYLOAD",
    "MANAGE_CHATS_PAYLOAD",
    "HELP_PAYLOAD",
    "has_connected_admin_chats",
    "build_home_keyboard",
    "build_home_text",
    "edit_to_home",
    "linked_addresses",
    "send_home",
]

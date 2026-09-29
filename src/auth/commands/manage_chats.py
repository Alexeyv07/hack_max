"""Управление адресами подключённых MAX-групп из личного меню администратора."""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from math import ceil
from typing import Any

from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from auth.commands.home import (
    MANAGE_CHATS_PAYLOAD,
    build_home_keyboard,
    build_home_text,
    has_connected_admin_chats,
)
from auth.handlers.managed_addresses import list_managed_addresses
from chat_link.handlers.group import announce_connected_group, announce_unlinked_group
from chat_link.handlers.registry import (
    AdminGroup,
    connected_admin_groups,
    eligible_admin_group,
)
from project.bot_media import home_image, other_messages_image
from project.database import session_scope
from project.logging_setup import get_logger
from user_chat.handlers import get_chat, list_chat_addresses, remove_chat_address

logger = get_logger(__name__)
PAGE_SIZE = 8
_LIST_PREFIX = "home:chats:list:"
_OPEN_PREFIX = "home:chats:open:"
_ADDRESS_PREFIX = "home:chats:address:"
_DELETE_PREFIX = "home:chats:delete:"


def _page(page: int, count: int) -> tuple[int, int]:
    pages = max(1, ceil(count / PAGE_SIZE))
    return max(0, min(page, pages - 1)), pages


def chat_list_view(groups: list[AdminGroup], page: int = 0) -> tuple[str, Any]:
    page, pages = _page(page, len(groups))
    builder = InlineKeyboardBuilder()
    for group in groups[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]:
        builder.row(
            CallbackButton(text=group.title[:120], payload=f"{_OPEN_PREFIX}{group.chat_id}")
        )
    if pages > 1:
        if page > 0:
            builder.row(CallbackButton(text="‹ Назад", payload=f"{_LIST_PREFIX}{page - 1}"))
        if page + 1 < pages:
            builder.row(CallbackButton(text="Далее ›", payload=f"{_LIST_PREFIX}{page + 1}"))
    builder.row(CallbackButton(text="Привязать чат", payload="chat_link:start:admin"))
    builder.row(CallbackButton(text="Назад", payload="home:addresses:home"))
    text = "<b>Выбор чатов для редактирования адресов</b>\n\nВыберите чат."
    if not groups:
        text = (
            "<b>Управление чатами</b>\n\n"
            "Сейчас нет доступных вам подключённых чатов. Можно привязать новый чат."
        )
    return text, builder.as_markup()


def chat_addresses_view(group: AdminGroup, addresses: list[Any]) -> tuple[str, Any]:
    builder = InlineKeyboardBuilder()
    for address in addresses:
        builder.row(
            CallbackButton(
                text=address.address_text[:120],
                payload=f"{_ADDRESS_PREFIX}{group.chat_id}:{address.id}",
            )
        )
    builder.row(
        CallbackButton(text="Добавить адрес", payload=f"chat_link:start:chat:{group.chat_id}")
    )
    builder.row(CallbackButton(text="Назад", payload=MANAGE_CHATS_PAYLOAD))
    return (
        f"<b>{escape(group.title)}</b>\n\nВыберите адрес для редактирования.",
        builder.as_markup(),
    )


def chat_address_view(group: AdminGroup, address: Any) -> tuple[str, Any]:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="Удалить адрес", payload=f"{_DELETE_PREFIX}{group.chat_id}:{address.id}"
        )
    )
    builder.row(CallbackButton(text="Назад", payload=f"{_OPEN_PREFIX}{group.chat_id}"))
    return (
        f"<b>Редактирование адреса</b>\n\n{escape(address.address_text)}\n"
        f"Чат: {escape(group.title)}",
        builder.as_markup(),
    )


def _parse_chat_address(payload: str, prefix: str) -> tuple[int, int] | None:
    try:
        chat_id, address_id = (int(value) for value in payload[len(prefix) :].split(":"))
    except ValueError:
        return None
    return (chat_id, address_id) if chat_id and address_id > 0 else None


async def show_chat_list(
    bot: Any, event: Any, max_user_id: int, show_screen: Callable[..., Any], page: int = 0
) -> None:
    try:
        with session_scope() as session:
            groups = await connected_admin_groups(bot, session, max_user_id=max_user_id)
    except Exception:
        logger.exception("Не удалось проверить чаты администратора")
        text, keyboard = (
            "Не удалось проверить чаты через MAX. Попробуйте ещё раз позже.",
            chat_list_view([])[1],
        )
    else:
        text, keyboard = chat_list_view(groups, page)
    await show_screen(
        bot, event, max_user_id, text, [other_messages_image(bot), keyboard], notification="Чаты"
    )


async def handle_manage_chats(
    bot: Any,
    event: Any,
    max_user_id: int,
    payload: str,
    show_screen: Callable[..., Any],
) -> None:
    """Каждое открытие и удаление повторно проверяет актуальные права через MAX."""
    if payload == MANAGE_CHATS_PAYLOAD or payload.startswith(_LIST_PREFIX):
        try:
            page = int(payload[len(_LIST_PREFIX) :]) if payload.startswith(_LIST_PREFIX) else 0
            if page < 0:
                raise ValueError
        except ValueError:
            await event.ack(notification="Некорректная кнопка")
            return
        await show_chat_list(bot, event, max_user_id, show_screen, page)
        return

    if payload.startswith(_OPEN_PREFIX):
        try:
            chat_id = int(payload[len(_OPEN_PREFIX) :])
        except ValueError:
            await event.ack(notification="Некорректная кнопка")
            return
        address_id = None
        action = "open"
    elif payload.startswith((_ADDRESS_PREFIX, _DELETE_PREFIX)):
        action = "delete" if payload.startswith(_DELETE_PREFIX) else "address"
        parsed = _parse_chat_address(
            payload, _DELETE_PREFIX if action == "delete" else _ADDRESS_PREFIX
        )
        if parsed is None:
            await event.ack(notification="Некорректная кнопка")
            return
        chat_id, address_id = parsed
    else:
        await event.ack(notification="Некорректная кнопка")
        return

    try:
        with session_scope() as session:
            group = await eligible_admin_group(
                bot, session, chat_id=chat_id, max_user_id=max_user_id
            )
            chat = get_chat(session, chat_id)
            if group is None or chat is None or chat.chat_type != "chat":
                text, keyboard = chat_list_view([])
                text = "Чат больше не доступен для управления."
            else:
                addresses = list_chat_addresses(session, chat_id)
                if action == "open":
                    text, keyboard = chat_addresses_view(group, addresses)
                else:
                    address = next((item for item in addresses if item.id == address_id), None)
                    if address is None:
                        text, keyboard = chat_addresses_view(group, addresses)
                        text += "\n\nЭтот адрес больше не привязан к чату."
                    elif action == "address":
                        text, keyboard = chat_address_view(group, address)
                    else:
                        removed = remove_chat_address(session, chat_id, address_id)
                        if removed:
                            # Действительное изменение подтверждаем только после commit.
                            session.flush()
        if (
            action == "delete"
            and group is not None
            and chat is not None
            and chat.chat_type == "chat"
            and address is not None
            and removed
        ):
            # Данные сохранены до отправки результата; сообщение в группе обновляем отдельно.
            try:
                if len(addresses) == 1:
                    await announce_unlinked_group(bot, chat_id)
                else:
                    await announce_connected_group(bot, chat_id)
            except Exception:
                logger.exception("Не удалось обновить объявление в чате после удаления адреса")
            with session_scope() as session:
                personal = [item.text for item in list_managed_addresses(session, max_user_id)]
                has_admin = await has_connected_admin_chats(bot, session, max_user_id)
            text = build_home_text(personal, notice="✅ Адрес успешно удалён из чата.")
            keyboard = build_home_keyboard(
                bot, has_addresses=bool(personal), has_admin_chats=has_admin
            )
            attachments = [home_image(bot), keyboard]
        else:
            attachments = [other_messages_image(bot), keyboard]
    except Exception:
        logger.exception("Не удалось управлять адресами группового чата")
        text, keyboard = chat_list_view([])
        text = "Не удалось проверить права или изменить адрес. Попробуйте ещё раз позже."
        attachments = [other_messages_image(bot), keyboard]
    await show_screen(bot, event, max_user_id, text, attachments, notification="Чаты")

"""KAN-32: список личных адресов и удаление из личного профиля MAX-бота."""

from __future__ import annotations

from html import escape
from math import ceil
from typing import Any

from maxapi import F
from maxapi.enums.format import Format
from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from auth.commands.home import (
    HELP_PAYLOAD,
    MANAGE_ADDRESSES_PAYLOAD,
    build_home_keyboard,
    build_home_text,
    has_connected_admin_chats,
)
from auth.commands.manage_chats import handle_manage_chats
from auth.handlers.managed_addresses import (
    ManagedAddress,
    list_managed_addresses,
    remove_managed_address,
)
from project.bot_media import home_image, other_messages_image
from project.database import session_scope
from project.docs_links import docs_html
from project.logging_setup import get_logger
from project.max_events import is_private_chat_event

logger = get_logger(__name__)
PAGE_SIZE = 8
_LIST_PREFIX = "home:addresses:list:"
_OPEN_PREFIX = "home:addresses:open:"
_DELETE_PREFIX = "home:addresses:delete:"
_HOME_PAYLOAD = "home:addresses:home"


def _page(page: int, count: int) -> tuple[int, int]:
    pages = max(1, ceil(count / PAGE_SIZE))
    return max(0, min(page, pages - 1)), pages


def _list_view(
    addresses: list[ManagedAddress], page: int, *, notice: str | None = None
) -> tuple[str, Any]:
    page, pages = _page(page, len(addresses))
    text = (
        "<b>Ваши адреса 🏠</b>\n\nВыберите адрес, чтобы посмотреть его или удалить.\n\n"
        f"{docs_html('Как управлять адресами', page='addresses')}"
    )
    if not addresses:
        text = (
            "<b>Ваши адреса 🏠</b>\n\nПока нет сохранённых адресов.\n\n"
            f"{docs_html('Как управлять адресами', page='addresses')}"
        )
    if notice:
        text += f"\n\n{escape(notice)}"
    builder = InlineKeyboardBuilder()
    for address in addresses[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]:
        builder.row(
            CallbackButton(
                text=address.text[:120],
                payload=f"{_OPEN_PREFIX}{address.id}:{page}",
            )
        )
    if pages > 1:
        navigation = []
        if page > 0:
            navigation.append(CallbackButton(text="‹", payload=f"{_LIST_PREFIX}{page - 1}"))
        navigation.append(
            CallbackButton(text=f"{page + 1}/{pages}", payload=f"{_LIST_PREFIX}{page}")
        )
        if page + 1 < pages:
            navigation.append(CallbackButton(text="›", payload=f"{_LIST_PREFIX}{page + 1}"))
        builder.row(*navigation)
    builder.row(CallbackButton(text="Добавить адрес", payload="chat_link:start:manage"))
    builder.row(CallbackButton(text="Назад", payload=_HOME_PAYLOAD))
    return text, builder.as_markup()


def _detail_view(address: ManagedAddress, page: int) -> tuple[str, Any]:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="Удалить адрес", payload=f"{_DELETE_PREFIX}{address.id}:{page}")
    )
    builder.row(CallbackButton(text="Назад", payload=f"{_LIST_PREFIX}{page}"))
    if address.chat_titles:
        chats = "\n".join(f"• {escape(title)}" for title in address.chat_titles)
    else:
        chats = "Не указан"
    text = (
        f"<b>{escape(address.text)}</b>\n\n"
        f"<b>{'Чаты' if len(address.chat_titles) > 1 else 'Чат'}:</b>\n{chats}\n\n"
        "Вы можете удалить этот адрес из своего списка.\n\n"
        f"{docs_html('Управление адресами', page='addresses')}"
    )
    return text, builder.as_markup()


def _delete_result_view(removed: bool) -> tuple[str, Any]:
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="На главную", payload=_HOME_PAYLOAD))
    text = "✅ Адрес успешно удалён." if removed else "Адрес уже удалён."
    return text, builder.as_markup()


def _parse_address_action(payload: str, prefix: str) -> tuple[int, int] | None:
    if not payload.startswith(prefix):
        return None
    parts = payload[len(prefix) :].split(":")
    if len(parts) != 2:
        return None
    try:
        address_id, page = map(int, parts)
    except ValueError:
        return None
    return (address_id, page) if address_id > 0 and page >= 0 else None


def build_manage_list_view(
    max_user_id: int, page: int = 0, *, notice: str | None = None
) -> tuple[str, Any]:
    """Экран списка адресов для возврата из chat_link (manage → добавить → назад)."""
    with session_scope() as session:
        addresses = list_managed_addresses(session, max_user_id)
        return _list_view(addresses, page, notice=notice)


async def _safe_ack(event: Any, notification: str = "…") -> None:
    """MAX требует message или notification в POST /answers — пустой ack даёт 400."""
    ack = getattr(event, "ack", None)
    if not callable(ack):
        return
    try:
        await ack(notification=notification)
    except Exception:
        logger.debug("Не удалось подтвердить callback", exc_info=True)


async def _show_screen(
    bot: Any,
    event: Any,
    max_user_id: int,
    text: str,
    attachments: list[Any],
    *,
    notification: str = "…",
) -> None:
    """Одно окно: правим сообщение кнопки через callback answer (без нового spam)."""
    edit = getattr(event, "edit", None)
    if callable(edit):
        try:
            await edit(
                text=text,
                attachments=attachments,
                format=Format.HTML,
                notify=False,
                notification=notification,
            )
            return
        except Exception:
            logger.debug("event.edit не удался, пробуем edit_message", exc_info=True)

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
            await _safe_ack(event, notification)
            return
        except Exception:
            logger.exception("Не удалось обновить экран управления адресами")

    await _safe_ack(event, notification)
    await bot.send_message(
        user_id=max_user_id,
        text=text,
        attachments=attachments,
        format=Format.HTML,
        brand_image=False,
    )


def register_manage_addresses(dp: Any, bot: Any) -> None:
    @dp.message_callback(F.callback.payload.startswith("home:"))
    async def on_manage_addresses_callback(event: Any) -> None:
        if not is_private_chat_event(event):
            await _safe_ack(event, "Продолжите в личном чате с ботом")
            return
        payload = str(getattr(event.callback, "payload", "") or "")
        max_user_id = int(event.callback.user.user_id)

        if payload.startswith("home:chats"):
            await handle_manage_chats(bot, event, max_user_id, payload, _show_screen)
            return

        if payload == HELP_PAYLOAD:
            builder = InlineKeyboardBuilder()
            builder.row(CallbackButton(text="На главную", payload=_HOME_PAYLOAD))
            await _show_screen(
                bot,
                event,
                max_user_id,
                f"<b>Помощь и обратная связь</b>\n\n{docs_html('О сервисе', page='overview')}",
                [other_messages_image(bot), builder.as_markup()],
                notification="Помощь",
            )
            return

        if payload == _HOME_PAYLOAD:
            with session_scope() as session:
                addresses = [item.text for item in list_managed_addresses(session, max_user_id)]
                text = build_home_text(addresses)
                has_admin_chats = await has_connected_admin_chats(bot, session, max_user_id)
            await _show_screen(
                bot,
                event,
                max_user_id,
                text,
                [
                    home_image(bot),
                    build_home_keyboard(
                        bot, has_addresses=bool(addresses), has_admin_chats=has_admin_chats
                    ),
                ],
                notification="Главная",
            )
            return

        if payload == MANAGE_ADDRESSES_PAYLOAD:
            page = 0
            action = "list"
            notice_label = "Адреса"
        elif payload.startswith(_LIST_PREFIX):
            try:
                page = int(payload[len(_LIST_PREFIX) :])
            except ValueError:
                await _safe_ack(event, "Некорректная команда")
                return
            action = "list"
            notice_label = "Адреса"
        elif payload.startswith(_OPEN_PREFIX):
            parsed = _parse_address_action(payload, _OPEN_PREFIX)
            if parsed is None:
                await _safe_ack(event, "Некорректная команда")
                return
            address_id, page = parsed
            action = "open"
            notice_label = "Адрес"
        elif payload.startswith(_DELETE_PREFIX):
            parsed = _parse_address_action(payload, _DELETE_PREFIX)
            if parsed is None:
                await _safe_ack(event, "Некорректная команда")
                return
            address_id, page = parsed
            action = "delete"
            notice_label = "Удалено"
        else:
            await _safe_ack(event, "Некорректная команда")
            return

        with session_scope() as session:
            if action == "delete":
                removed = remove_managed_address(
                    session, max_user_id=max_user_id, address_id=address_id
                )
                text, keyboard = _delete_result_view(removed)
            else:
                addresses = list_managed_addresses(session, max_user_id)
                if action == "open":
                    address = next((item for item in addresses if item.id == address_id), None)
                    text, keyboard = (
                        _detail_view(address, page)
                        if address is not None
                        else _list_view(addresses, page, notice="Адрес больше недоступен.")
                    )
                else:
                    text, keyboard = _list_view(addresses, page)

        await _show_screen(
            bot,
            event,
            max_user_id,
            text,
            [other_messages_image(bot), keyboard],
            notification=notice_label,
        )

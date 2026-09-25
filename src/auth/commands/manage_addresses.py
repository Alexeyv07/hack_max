"""KAN-32: список личных адресов и удаление из личного профиля MAX-бота."""

from __future__ import annotations

from html import escape
from math import ceil
from typing import Any

from maxapi import F
from maxapi.enums.format import Format
from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from auth.commands.home import MANAGE_ADDRESSES_PAYLOAD, send_home
from auth.handlers.managed_addresses import (
    ManagedAddress,
    list_managed_addresses,
    remove_managed_address,
)
from project.database import session_scope
from project.logging_setup import get_logger

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
    text = "<b>Ваши адреса 🏠</b>\n\nВыберите адрес, чтобы посмотреть его или удалить."
    if not addresses:
        text = "<b>Ваши адреса 🏠</b>\n\nПока нет сохранённых адресов."
    if notice:
        text += f"\n\n{escape(notice)}"
    builder = InlineKeyboardBuilder()
    if not addresses:
        builder.row(CallbackButton(text="Указать свой адрес", payload="chat_link:start"))
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
    builder.row(CallbackButton(text="← Главная", payload=_HOME_PAYLOAD))
    return text, builder.as_markup()


def _detail_view(address: ManagedAddress, page: int) -> tuple[str, Any]:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="Удалить адрес", payload=f"{_DELETE_PREFIX}{address.id}:{page}")
    )
    builder.row(CallbackButton(text="← Назад", payload=f"{_LIST_PREFIX}{page}"))
    text = (
        f"<b>{escape(address.text)}</b>\n\n"
        "Вы можете удалить этот адрес из своего списка. "
        "Привязка дома к групповому чату при этом сохранится."
    )
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


async def _show(
    bot: Any, event: Any, max_user_id: int, text: str, keyboard: Any, *, fresh: bool
) -> None:
    if not fresh:
        mid = getattr(getattr(getattr(event, "message", None), "body", None), "mid", None)
        if mid:
            try:
                await bot.edit_message(
                    str(mid), text=text, attachments=[keyboard], format=Format.HTML, notify=False
                )
                return
            except Exception:
                logger.exception("Не удалось обновить экран управления адресами")
    # Открываем отдельное сообщение: фото главной не заменяется текстом.
    await bot.send_message(
        user_id=max_user_id, text=text, attachments=[keyboard], format=Format.HTML
    )


def register_manage_addresses(dp: Any, bot: Any) -> None:
    @dp.message_callback(F.callback.payload.startswith("home:"))
    async def on_manage_addresses_callback(event: Any) -> None:
        payload = str(getattr(event.callback, "payload", "") or "")
        max_user_id = int(event.callback.user.user_id)
        if payload == _HOME_PAYLOAD:
            await event.ack(notification="Открываю главную")
            with session_scope() as session:
                await send_home(bot, session, max_user_id)
            return
        if payload == MANAGE_ADDRESSES_PAYLOAD:
            page = 0
            action = "list"
        elif payload.startswith(_LIST_PREFIX):
            try:
                page = int(payload[len(_LIST_PREFIX) :])
            except ValueError:
                await event.ack(notification="Некорректная команда")
                return
            action = "list"
        elif payload.startswith(_OPEN_PREFIX):
            parsed = _parse_address_action(payload, _OPEN_PREFIX)
            if parsed is None:
                await event.ack(notification="Некорректная команда")
                return
            address_id, page = parsed
            action = "open"
        elif payload.startswith(_DELETE_PREFIX):
            parsed = _parse_address_action(payload, _DELETE_PREFIX)
            if parsed is None:
                await event.ack(notification="Некорректная команда")
                return
            address_id, page = parsed
            action = "delete"
        else:
            await event.ack(notification="Некорректная команда")
            return
        await event.ack(notification="Открываю адреса")
        with session_scope() as session:
            if action == "delete":
                removed = remove_managed_address(
                    session, max_user_id=max_user_id, address_id=address_id
                )
                addresses = list_managed_addresses(session, max_user_id)
                text, keyboard = _list_view(
                    addresses, page, notice="✅ Адрес удалён." if removed else "Адрес уже удалён."
                )
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
        await _show(
            bot, event, max_user_id, text, keyboard, fresh=payload == MANAGE_ADDRESSES_PAYLOAD
        )

from __future__ import annotations

import math
from typing import Any

from maxapi.types import CallbackButton, ClipboardButton, LinkButton, OpenAppButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from address.street_catalog import normalize_ui_text


def page_size(count: int, *, max_items: int = 12) -> int:
    """Подобрать размер страницы без десятков кнопок и сотен страниц."""
    if count <= 0:
        return 1
    if count <= max_items:
        return count
    return max(6, min(max_items, math.ceil(count / 6)))


def paginate(
    values: list[Any],
    page: int,
    *,
    max_items: int = 12,
) -> tuple[list[Any], int, int]:
    size = page_size(len(values), max_items=max_items)
    pages = max(1, math.ceil(len(values) / size))
    page = max(0, min(page, pages - 1))
    start = page * size
    return values[start : start + size], page, pages


def list_keyboard(
    values: list[str],
    *,
    kind: str,
    page: int = 0,
    back: str = "root",
):
    is_house = kind in {"house", "postal_house"}

    max_items = 18 if is_house else 12
    items, page, pages = paginate(values, page, max_items=max_items)
    size = page_size(len(values), max_items=max_items)
    builder = InlineKeyboardBuilder()

    columns = 1
    if is_house and items:
        longest = max(len(value) for value in items)

        if longest <= 6 and len(items) >= 6:
            columns = 3
        elif longest <= 14 and len(items) >= 4:
            columns = 2

    buttons = [
        CallbackButton(
            text=value[:120],
            payload=f"cl:{kind}:pick:{idx}",
        )
        for idx, value in enumerate(items, start=page * size)
    ]

    for start in range(0, len(buttons), columns):
        builder.row(*buttons[start : start + columns])

    builder.row(
        CallbackButton(
            text="← Назад",
            payload=f"cl:back:{back}",
        )
    )

    nav: list[CallbackButton] = []

    if page > 0:
        nav.append(
            CallbackButton(
                text="←",
                payload=f"cl:{kind}:page:{page - 1}",
            )
        )

    if page + 1 < pages:
        nav.append(
            CallbackButton(
                text="→",
                payload=f"cl:{kind}:page:{page + 1}",
            )
        )

    if nav:
        builder.row(*nav)

    if pages >= 10:
        fast: list[CallbackButton] = []

        if page >= 5:
            fast.append(
                CallbackButton(
                    text="-5",
                    payload=f"cl:{kind}:page:{page - 5}",
                )
            )

        if page + 5 < pages:
            fast.append(
                CallbackButton(
                    text="+5",
                    payload=f"cl:{kind}:page:{page + 5}",
                )
            )

        if fast:
            builder.row(*fast)

    return builder.as_markup(), page, pages


def existing_chats_keyboard(chats: list[Any]):
    """Ссылки на уже подключённые группы: без callback и auto-add пользователя."""
    builder = InlineKeyboardBuilder()
    for chat in chats[:12]:
        if not chat.invite_link:
            continue
        builder.row(LinkButton(text=(chat.title or "Домовой чат")[:64], url=chat.invite_link))
    builder.row(CallbackButton(text="← Выбрать другой адрес", payload="cl:method:native"))
    return builder.as_markup()


def method_keyboard(bot: Any):
    me = getattr(bot, "me", None)
    username = getattr(me, "username", None)
    contact_id = getattr(me, "user_id", None)

    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="Выбрать место жительства", payload="cl:method:native"))
    builder.row(CallbackButton(text="Указать почтовый индекс", payload="cl:method:postal"))
    builder.row(
        OpenAppButton(
            text="Указать на карте",
            web_app=username,
            contact_id=contact_id,
            payload="chat_link_map",
        )
    )
    builder.row(
        OpenAppButton(
            text="Ввести текстом",
            web_app=username,
            contact_id=contact_id,
            payload="chat_link_text",
        )
    )
    return builder.as_markup()


def prefix_groups(values: list[str], *, base_prefix: str = "") -> list[str]:
    """Редкое дополнительное сужение очень длинного списка улиц."""
    compact = [
        "".join(char for char in normalize_ui_text(value) if char.isalnum()) for value in values
    ]
    start = max(1, len(base_prefix) + 1)
    for length in range(start, start + 4):
        groups = sorted({value[:length] for value in compact if value.startswith(base_prefix)})
        if not 2 <= len(groups) <= 12:
            continue
        largest = max(sum(1 for value in compact if value.startswith(group)) for group in groups)
        if largest <= 72:
            return groups
    return sorted({value[: start + 1] for value in compact if value.startswith(base_prefix)})


def setup_keyboard(admin_link: str | None):
    builder = InlineKeyboardBuilder()
    if admin_link:
        builder.row(ClipboardButton(text="Скопировать ссылку для админа", payload=admin_link))
    builder.row(CallbackButton(text="← Выбрать другой адрес", payload="cl:method:native"))
    return builder.as_markup()

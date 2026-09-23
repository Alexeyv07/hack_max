from __future__ import annotations

from typing import Any

from maxapi.types import CallbackButton, ClipboardButton, LinkButton, OpenAppButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from address.street_catalog import normalize_ui_text
from chat_link.commands.pagination import HOUSE_PAGE_SIZE, JUMP_PAGES, PAGE_SIZE, paginate


def list_keyboard(
    values: list[str],
    *,
    kind: str,
    page: int = 0,
    back: str = "root",
):
    """Компактная пагинация picker-а с отдельной сеткой для номеров домов."""
    is_house = kind in {"house", "postal_house"}
    page_size = HOUSE_PAGE_SIZE if is_house else PAGE_SIZE
    current = paginate(values, page, page_size=page_size)
    builder = InlineKeyboardBuilder()

    # Номера домов короткие: 15 элементов = ровно 5 полных рядов по 3 кнопки.
    # Остальные списки оставляем в одну колонку, но ограничиваем 10 строками.
    columns = 3 if is_house else 1

    buttons = [
        CallbackButton(
            text=value[:120],
            payload=f"cl:{kind}:pick:{idx}",
        )
        for idx, value in current.items
    ]
    for start in range(0, len(buttons), columns):
        builder.row(*buttons[start : start + columns])

    if current.pages > 1:
        nav: list[CallbackButton] = []
        if current.pages > 10:
            jump_back = max(0, current.index - JUMP_PAGES)
            nav.append(
                CallbackButton(
                    text=f"«{JUMP_PAGES}" if current.index > 0 else "·",
                    payload=(f"cl:{kind}:page:{jump_back}" if current.index > 0 else "cl:noop"),
                )
            )
        nav.append(
            CallbackButton(
                text="‹" if current.has_previous else "·",
                payload=(
                    f"cl:{kind}:page:{current.index - 1}" if current.has_previous else "cl:noop"
                ),
            )
        )
        nav.append(
            CallbackButton(
                text=f"{current.index + 1} / {current.pages}",
                payload="cl:noop",
            )
        )
        nav.append(
            CallbackButton(
                text="›" if current.has_next else "·",
                payload=(f"cl:{kind}:page:{current.index + 1}" if current.has_next else "cl:noop"),
            )
        )
        if current.pages > 10:
            jump_forward = min(current.pages - 1, current.index + JUMP_PAGES)
            nav.append(
                CallbackButton(
                    text=f"{JUMP_PAGES}»" if current.has_next else "·",
                    payload=(f"cl:{kind}:page:{jump_forward}" if current.has_next else "cl:noop"),
                )
            )
        builder.row(*nav)

    builder.row(CallbackButton(text="← Назад", payload=f"cl:back:{back}"))
    return builder.as_markup(), current.index, current.pages


def method_keyboard(
    bot: Any, *, target_chat_id: int | None = None, resident_chat_id: int | None = None
):
    me = getattr(bot, "me", None)
    username = getattr(me, "username", None)
    contact_id = getattr(me, "user_id", None)

    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="Выбрать место жительства", payload="cl:method:native"))
    builder.row(CallbackButton(text="Указать почтовый индекс", payload="cl:method:postal"))
    suffix = (
        f"_bind_{target_chat_id}"
        if target_chat_id is not None
        else f"_resident_{resident_chat_id}"
        if resident_chat_id is not None
        else ""
    )
    builder.row(
        OpenAppButton(
            text="Указать на карте",
            web_app=username,
            contact_id=contact_id,
            payload=f"chat_link_map{suffix}",
        )
    )
    builder.row(
        OpenAppButton(
            text="Ввести текстом",
            web_app=username,
            contact_id=contact_id,
            payload=f"chat_link_text{suffix}",
        )
    )
    builder.row(CallbackButton(text="← Назад", payload="cl:back:welcome"))
    return builder.as_markup()


def postal_input_keyboard():
    """Выход из ручного ввода индекса, в том числе после ошибки."""
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="← Назад", payload="cl:back:root"))
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
    """Экран обычного жителя после выбора дома."""
    builder = InlineKeyboardBuilder()
    if admin_link:
        builder.row(ClipboardButton(text="Скопировать ссылку для админа", payload=admin_link))
    builder.row(CallbackButton(text="Я администратор чата", payload="cl:admin:help"))
    builder.row(CallbackButton(text="← Выбрать другой адрес", payload="cl:method:native"))
    return builder.as_markup()


def admin_setup_keyboard():
    """Экран инструкций для администратора после выбора дома."""
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="← Я не администратор", payload="cl:admin:user"))
    builder.row(CallbackButton(text="← Выбрать другой адрес", payload="cl:method:native"))
    return builder.as_markup()


def group_referral_keyboard(referral: str | None):
    if not referral:
        return None
    builder = InlineKeyboardBuilder()
    builder.row(LinkButton(text="Привязать дом", url=referral))
    return builder.as_markup()

"""Экраны жителя при выборе адреса уже подключённого домового чата."""

from __future__ import annotations

from html import escape

from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def residence_success_text(address_text: str) -> str:
    return f"✅ Чат успешно добавлен.\n\nАдрес: {escape(address_text)}"


def residence_wait_text(address_text: str) -> str:
    return (
        f"Адрес: {escape(address_text)}\n\n"
        "Вы пока не состоите в домовом чате. Присоединитесь к нему через сервис "
        "«Госуслуги Дом» и нажмите «Проверить еще раз»."
    )


def residence_result_keyboard(
    address_id: int, *, member: bool, resident_chat_id: int | None = None
):
    builder = InlineKeyboardBuilder()
    if member:
        builder.row(CallbackButton(text="На главную", payload="home:addresses:home"))
    else:
        retry = f"cl:residence:retry:{address_id}"
        if resident_chat_id is not None:
            retry += f":{resident_chat_id}"
        builder.row(CallbackButton(text="Проверить еще раз", payload=retry))
        builder.row(CallbackButton(text="Назад", payload="cl:residence:back"))
    return builder.as_markup()

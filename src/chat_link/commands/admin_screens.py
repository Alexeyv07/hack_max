"""Общие тексты и кнопки сценария подключения первого домового чата."""

from __future__ import annotations

from html import escape

from maxapi.types import CallbackButton, ClipboardButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from chat_link.handlers.registry import AdminGroup


def no_chat_text(address_text: str) -> str:
    return (
        f"<b>Адрес выбран</b>\n{escape(address_text)}\n\n"
        "Для этого дома пока нет подключённого чата. Если вы обычный житель, "
        "отправьте администратору домового чата приглашение кнопкой ниже."
    )


def invitation_text(address_text: str, admin_link: str) -> str:
    return (
        f"Здравствуйте! Предлагаю подключить домовой чат по адресу {address_text} "
        "к боту «КасаетсяМеня». Он собирает важные новости о доме, отключениях, "
        "ремонте и изменениях сроков, формирует краткую ленту и уведомления, "
        "чтобы жителям не приходилось перечитывать весь чат. "
        "Администратору нужно добавить бота в группу и дать ему право читать все сообщения. "
        f"Начать подключение: {admin_link}"
    )


def invitation_preview(text: str) -> str:
    return "Пригласительное сообщение:\n\n" + escape(text)


def invitation_keyboard(*, address_id: int, text: str):
    builder = InlineKeyboardBuilder()
    builder.row(ClipboardButton(text="Скопировать", payload=text))
    builder.row(CallbackButton(text="Назад", payload=f"cl:admin:back:{address_id}"))
    return builder.as_markup()


def waiting_admin_text(address_text: str, *, failed: bool = False) -> str:
    intro = (
        "Привязка адреса пока не завершена. Проверьте, что бот находится в нужном чате, "
        "назначен администратором и имеет все необходимые права, включая «Читать все сообщения»."
        if failed
        else "Добавьте бота в нужный групповой чат и назначьте администратором "
        "с правом «Читать все сообщения»."
    )
    return (
        f"<b>Адрес выбран</b>\n{escape(address_text)}\n\n"
        f"{intro}\n\n"
        "После этого нажмите «Проверить еще раз». Адрес сохранён, повторно выбирать его не нужно."
    )


def waiting_admin_keyboard(address_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="Проверить еще раз", payload=f"cl:admin:retry:{address_id}"))
    builder.row(CallbackButton(text="Назад", payload=f"cl:admin:back:{address_id}"))
    return builder.as_markup()


def admin_groups_keyboard(address_id: int, groups: list[AdminGroup]):
    builder = InlineKeyboardBuilder()
    for group in groups:
        builder.row(
            CallbackButton(
                text=group.title[:120], payload=f"cl:admin:pick:{address_id}:{group.chat_id}"
            )
        )
    builder.row(CallbackButton(text="Назад", payload=f"cl:admin:back:{address_id}"))
    return builder.as_markup()


def admin_confirm_text(address_text: str, group: AdminGroup) -> str:
    return (
        "<b>Подтвердите привязку</b>\n\n"
        f"Адрес: {escape(address_text)}\n"
        f"Чат: {escape(group.title)}\n\n"
        "Привязать этот адрес к выбранному групповому чату?"
    )


def admin_confirm_keyboard(address_id: int, chat_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="Подтвердить", payload=f"cl:admin:confirm:{address_id}:{chat_id}")
    )
    builder.row(CallbackButton(text="Назад", payload=f"cl:admin:retry:{address_id}"))
    return builder.as_markup()


def admin_success_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="На главную", payload="cl:admin:home"))
    return builder.as_markup()

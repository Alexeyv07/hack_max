"""Авторизация и первый экран бота."""

from __future__ import annotations

import asyncio
from html import escape
from time import monotonic
from typing import Any

from maxapi.enums.format import Format
from maxapi.filters.command import CommandStart
from maxapi.types import CallbackButton, OpenAppButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from auth.handlers.authorize import authorize_from_event
from chat_link.handlers import bind_referral_member, claim_admin_request
from project.config import get_settings
from project.database import session_scope
from user_chat.handlers import has_connected_chat

CHAT_LINK_START_PAYLOAD = "chat_link:start"
CHAT_BIND_PREFIX = "chat_bind_"


def build_welcome_text(
    name: str,
    *,
    admin_token: str | None = None,
    notice: str | None = None,
    binding_group: bool = False,
    choosing_residence: bool = False,
) -> str:
    safe_name = escape(name)
    docs_url = get_settings().docs.url
    text = (
        f"Привет, {safe_name}! Я помогу следить за важными событиями "
        "рядом с вашим домом и в районе.\n\n"
        f'🔗 <a href="{docs_url}"><b>Подробнее о проекте</b></a>'
    )
    if notice:
        text += f"\n\n{escape(notice)}"
    if admin_token:
        text += (
            "\n\nВас попросили подключить домовой чат. Добавьте бота в нужный "
            "групповой чат и назначьте его администратором с правом "
            "«Читать все сообщения». После этого привязка завершится автоматически."
        )
    if binding_group:
        text += (
            "\n\nВы подключаете уже добавленный групповой чат. "
            "Вы можете добавить к нему несколько адресов, например все дома вашего двора."
        )
    if choosing_residence:
        text += (
            "\n\nЧтобы показывать события рядом именно с вашим домом, "
            "укажите свой адрес. Чат может объединять несколько домов."
        )
    return text


def build_welcome_keyboard(
    bot: Any,
    *,
    show_events: bool,
    binding_group: bool = False,
    choosing_residence: bool = False,
) -> Any:
    me = getattr(bot, "me", None)
    username = getattr(me, "username", None)
    user_id = getattr(me, "user_id", None)
    keyboard = InlineKeyboardBuilder()
    add_text = (
        "Указать свой адрес"
        if choosing_residence
        else "Добавить адрес чата"
        if binding_group
        else "Добавить чат"
    )
    buttons: list[Any] = [CallbackButton(text=add_text, payload=CHAT_LINK_START_PAYLOAD)]
    if show_events:
        buttons.append(OpenAppButton(text="Смотреть события", web_app=username, contact_id=user_id))
    keyboard.row(*buttons)
    return keyboard.as_markup()


def _display_name(user: Any) -> str:
    return user.name or user.username or "друг"


def _show_events(max_user_id: int) -> bool:
    with session_scope() as session:
        return has_connected_chat(session, max_user_id)


def _claim_admin(*, token: str, max_user_id: int) -> None:
    with session_scope() as session:
        claim_admin_request(session, token=token, max_user_id=max_user_id)


def _sent_mid(result: Any) -> str | None:
    message = getattr(result, "message", None)
    body = getattr(message, "body", None)
    mid = getattr(body, "mid", None)
    return str(mid) if mid else None


async def _render_welcome(
    bot: Any,
    event: Any,
    context: Any,
    user: Any,
    *,
    admin_token: str | None = None,
    notice: str | None = None,
    target_chat_id: int | None = None,
    resident_chat_id: int | None = None,
    recipient_chat_id: int | None = None,
) -> None:
    text = build_welcome_text(
        _display_name(user),
        admin_token=admin_token,
        notice=notice,
        binding_group=target_chat_id is not None,
        choosing_residence=resident_chat_id is not None,
    )
    show_events = await asyncio.to_thread(_show_events, user.max_user_id)
    attachments = [
        build_welcome_keyboard(
            bot,
            show_events=show_events,
            binding_group=target_chat_id is not None,
            choosing_residence=resident_chat_id is not None,
        )
    ]
    await context.clear()
    if target_chat_id is not None:
        await context.update_data(target_chat_id=target_chat_id)
    if resident_chat_id is not None:
        await context.update_data(resident_chat_id=resident_chat_id)
    # Каждый /start создаёт новый экран в конце переписки; прежние не редактируем.
    chat_id = (
        recipient_chat_id if recipient_chat_id is not None else getattr(event, "chat_id", None)
    )
    if chat_id is None:
        message = getattr(event, "message", None)
        recipient = getattr(message, "recipient", None)
        chat_id = getattr(recipient, "chat_id", None)
    if chat_id is not None:
        result = await bot.send_message(
            chat_id=chat_id,
            text=text,
            attachments=attachments,
            format=Format.HTML,
        )
    else:
        result = await event.message.answer(
            text=text,
            attachments=attachments,
            format=Format.HTML,
        )
    mid = _sent_mid(result)
    if mid:
        await context.update_data(flow_mid=mid)


def register_auth_commands(dp: Any, bot: Any) -> None:
    recent_starts: dict[int, tuple[str, float]] = {}

    def duplicate_start(user_id: int, source: str, *, allow_skip: bool = True) -> bool:
        """Снять дубликат одного запуска из bot_started и message_created."""
        now = monotonic()
        previous = recent_starts.get(user_id)
        if (
            allow_skip
            and previous is not None
            and previous[0] != source
            and now - previous[1] < 1.5
        ):
            return True
        recent_starts[user_id] = (source, now)
        return False

    @dp.bot_started()
    async def on_bot_started(event: Any, context: Any) -> None:
        user = await asyncio.to_thread(authorize_from_event, event)
        if user is None:
            return
        payload = getattr(event, "payload", None) or ""
        # Deep-link всегда обрабатываем: он может содержать привязку чата.
        if duplicate_start(user.max_user_id, "bot_started", allow_skip=not payload):
            return
        admin_token = (
            payload.removeprefix("chat_admin_") if payload.startswith("chat_admin_") else None
        )
        target_chat_id = None
        resident_chat_id = None
        notice = None
        if payload.startswith(CHAT_BIND_PREFIX):
            try:
                parsed_chat_id = int(payload.removeprefix(CHAT_BIND_PREFIX))
            except ValueError:
                notice = "Ссылка на подключение чата некорректна."
            else:
                target_chat_id = parsed_chat_id
        if admin_token:
            try:
                await asyncio.to_thread(
                    _claim_admin,
                    token=admin_token,
                    max_user_id=user.max_user_id,
                )
            except ValueError as exc:
                notice = str(exc)
        if (
            payload.startswith("chat_")
            and not payload.startswith("chat_admin_")
            and not payload.startswith(CHAT_BIND_PREFIX)
        ):
            try:
                chat_id = int(payload.removeprefix("chat_"))
            except ValueError:
                notice = "Ссылка на домовой чат некорректна."
            else:
                with session_scope() as session:
                    outcome = await bind_referral_member(
                        bot,
                        session,
                        chat_id=chat_id,
                        max_user_id=user.max_user_id,
                    )
                notice = outcome.message
                if outcome.joined:
                    resident_chat_id = chat_id
        await _render_welcome(
            bot,
            event,
            context,
            user,
            admin_token=admin_token,
            notice=notice,
            target_chat_id=target_chat_id,
            resident_chat_id=resident_chat_id,
        )

    @dp.message_created(CommandStart())
    async def on_start(event: Any, context: Any) -> None:
        user = await asyncio.to_thread(authorize_from_event, event)
        if user is None or duplicate_start(user.max_user_id, "message_created"):
            return
        await _render_welcome(bot, event, context, user)

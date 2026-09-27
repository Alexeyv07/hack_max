"""Авторизация и первый экран бота."""

from __future__ import annotations

import asyncio
from html import escape
from time import monotonic
from typing import Any

from maxapi.enums.format import Format
from maxapi.filters.command import Command, CommandStart
from maxapi.types import CallbackButton, OpenAppButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from auth.commands.home import send_home
from auth.commands.manage_addresses import register_manage_addresses
from auth.handlers.authorize import authorize_from_event
from auth.handlers.residence import get_personal_address
from chat_link.handlers import bind_referral_member, claim_admin_request
from project.bot_media import first_start_image
from project.bot_screens import remember_screen, send_screen
from project.database import session_scope
from project.docs_links import docs_html
from project.logging_setup import get_logger
from project.max_events import is_private_chat_event
from user_chat.handlers import has_connected_chat, linked_group_ids

logger = get_logger(__name__)
CHAT_LINK_START_PAYLOAD = "chat_link:start"
CHAT_BIND_PREFIX = "chat_bind_"

ADDRESS_PICKER_TEXT = (
    "Давайте найдём ваш дом 🏠\n\n"
    "Выберите удобный способ: найти адрес в списке, показать дом на карте "
    "или написать адрес.\n\n"
    "Если помните почтовый индекс, можно начать с него — затем выбрать свой дом.\n\n"
    f"{docs_html('Как выбрать адрес', page='chat-link')}"
)


def build_welcome_text(
    name: str,
    *,
    admin_token: str | None = None,
    notice: str | None = None,
    binding_group: bool = False,
    choosing_residence: bool = False,
    can_choose_address: bool = True,
) -> str:
    safe_name = escape(name)
    text = (
        f"Здравствуйте, {safe_name}!\n\n"
        "Это сервис «КасаетсяМеня» 🕊️\n\n"
        "- Помогаем не пропустить важное о вашем доме: когда отключат воду, "
        "где идут работы и что изменилось 👷‍♂️\n\n"
        "- Вам не нужно перечитывать весь чат соседей 🙋\n\n"
        "- Мы собираем сообщения об одном событии в понятную карточку: "
        "<b>что произойдёт, когда и касается ли это вашего дома и корпуса.</b> 🚀\n\n"
        "- Если сроки изменятся — обновим информацию 📣\n\n"
        "Также кроме новостей вашего двора и округи мы собираем для вас "
        "подборку актуальных новостей вашего города. Не упустите то, что вас касается ❗\n\n"
        f"{docs_html('О сервисе', page='overview')}\n\n"
        "Укажите свой адрес, чтобы подключить сервис к чату вашего дома:"
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
    can_choose_address: bool = True,
) -> Any:
    me = getattr(bot, "me", None)
    username = getattr(me, "username", None)
    user_id = getattr(me, "user_id", None)
    keyboard = InlineKeyboardBuilder()
    buttons: list[Any] = []
    if binding_group or can_choose_address:
        add_text = "Добавить адрес чата" if binding_group else "Выбрать адрес"
        buttons.append(CallbackButton(text=add_text, payload=CHAT_LINK_START_PAYLOAD))
    if show_events:
        buttons.append(
            OpenAppButton(text="Посмотреть новости рядом", web_app=username, contact_id=user_id)
        )
    if buttons:
        keyboard.row(*buttons)
    return keyboard.as_markup() if buttons else None


def _display_name(user: Any) -> str:
    return user.name or user.username or "друг"


def _can_choose_address(max_user_id: int) -> bool:
    return True  # Адрес может выбрать любой; право на ленту проверим после выбора дома.


def user_can_see_events(max_user_id: int) -> bool:
    """Единая проверка доступа к ленте: личный дом+чат или любое подключённое членство."""
    with session_scope() as session:
        personal = get_personal_address(session, max_user_id)
        return (
            personal is not None
            and bool(linked_group_ids(session, max_user_id, address_id=personal.id))
        ) or has_connected_chat(session, max_user_id)


# Совместимость со старыми тестами / импортами.
_show_events = user_can_see_events


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
    can_choose_address = await asyncio.to_thread(_can_choose_address, user.max_user_id)
    can_choose_address = (
        can_choose_address or target_chat_id is not None or resident_chat_id is not None
    )
    text = build_welcome_text(
        _display_name(user),
        admin_token=admin_token,
        notice=notice,
        binding_group=target_chat_id is not None,
        choosing_residence=resident_chat_id is not None,
        can_choose_address=can_choose_address,
    )
    show_events = await asyncio.to_thread(_show_events, user.max_user_id)
    keyboard = build_welcome_keyboard(
        bot,
        show_events=show_events,
        binding_group=target_chat_id is not None,
        choosing_residence=resident_chat_id is not None,
        can_choose_address=can_choose_address,
    )
    attachments = [keyboard] if keyboard is not None else []
    previous_mid = (await context.get_data()).get("flow_mid")
    await context.clear()
    if target_chat_id is not None:
        await context.update_data(target_chat_id=target_chat_id)
    if resident_chat_id is not None:
        await context.update_data(resident_chat_id=resident_chat_id)
    # /start создаёт новый экран внизу; старый навигационный экран убираем после отправки.
    chat_id = (
        recipient_chat_id if recipient_chat_id is not None else getattr(event, "chat_id", None)
    )
    if chat_id is None:
        message = getattr(event, "message", None)
        recipient = getattr(message, "recipient", None)
        chat_id = getattr(recipient, "chat_id", None)
    is_new = getattr(user, "is_new", False)
    render_home = (
        show_events
        and not is_new
        and not any((admin_token, notice, target_chat_id, resident_chat_id))
    )
    if render_home:
        with session_scope() as session:
            result = await send_home(bot, session, user.max_user_id, recipient_chat_id=chat_id)
    else:
        # Полная презентация сервиса и её обложка — только при первом входе.
        # При повторном /start без адреса сразу предлагаем выбор дома.
        screen_text = (
            text
            if is_new or any((admin_token, notice, target_chat_id, resident_chat_id))
            else ADDRESS_PICKER_TEXT
        )
        screen_attachments = [first_start_image(bot), *attachments] if is_new else attachments
        if chat_id is not None:
            result = await send_screen(
                bot,
                user.max_user_id,
                previous_mid=previous_mid,
                chat_id=chat_id,
                text=screen_text,
                attachments=screen_attachments,
                format=Format.HTML,
            )
        else:
            result = await send_screen(
                bot,
                user.max_user_id,
                previous_mid=previous_mid,
                user_id=user.max_user_id,
                text=screen_text,
                attachments=screen_attachments,
                format=Format.HTML,
            )
    mid = _sent_mid(result)
    if mid:
        await remember_screen(bot, user.max_user_id, mid, previous_mid=previous_mid)
        await context.update_data(flow_mid=mid)
        if is_new and not render_home:
            await context.update_data(first_welcome_mid=mid)


def register_auth_commands(dp: Any, bot: Any) -> None:
    register_manage_addresses(dp, bot)

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

    @dp.message_created(Command("home"))
    async def on_home(event: Any, context: Any = None) -> None:
        """Показать главную новым экраном после команды пользователя."""
        if not is_private_chat_event(event):
            return
        user = await asyncio.to_thread(authorize_from_event, event)
        if user is None:
            return
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            recipient = getattr(getattr(event, "message", None), "recipient", None)
            chat_id = getattr(recipient, "chat_id", None)
        try:
            with session_scope() as session:
                result = await send_home(bot, session, user.max_user_id, recipient_chat_id=chat_id)
            previous_mid = (await context.get_data()).get("flow_mid") if context else None
            mid = _sent_mid(result)
            await remember_screen(bot, user.max_user_id, mid, previous_mid=previous_mid)
            if context is not None and mid:
                await context.clear()
                await context.update_data(flow_mid=mid)
        except Exception:
            logger.exception("Не удалось отправить /home")

    @dp.bot_started()
    async def on_bot_started(event: Any, context: Any) -> None:
        if not is_private_chat_event(event):
            return
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
        if not is_private_chat_event(event):
            return
        user = await asyncio.to_thread(authorize_from_event, event)
        if user is None or duplicate_start(user.max_user_id, "message_created"):
            return
        await _render_welcome(bot, event, context, user)

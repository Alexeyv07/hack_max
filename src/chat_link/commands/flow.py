from __future__ import annotations

import asyncio
from typing import Any

from maxapi import F
from maxapi.enums.format import Format
from maxapi.utils.deep_linking import create_start_link

from address.street_catalog import normalize_ui_text
from auth.commands.home import edit_to_home, send_home
from auth.commands.manage_addresses import build_manage_list_view
from auth.commands.manage_chats import chat_list_view
from auth.commands.start import ADDRESS_PICKER_TEXT, build_welcome_keyboard, user_can_see_events
from auth.handlers import get_user_by_max_id
from auth.handlers.residence import set_personal_address
from chat_link.commands.admin_screens import (
    admin_confirm_keyboard,
    admin_confirm_text,
    admin_groups_keyboard,
    admin_success_keyboard,
    invitation_keyboard,
    invitation_preview,
    invitation_text,
    no_chat_text,
    waiting_admin_keyboard,
    waiting_admin_text,
)
from chat_link.commands.keyboards import (
    list_keyboard,
    method_keyboard,
    postal_input_keyboard,
    prefix_groups,
    setup_keyboard,
)
from chat_link.commands.residence_screens import (
    residence_result_keyboard,
    residence_success_text,
    residence_wait_text,
)
from chat_link.commands.states import ChatLinkStates
from chat_link.handlers import (
    announce_connected_group,
    announce_group_address_setup,
    bind_existing_chat_member,
    bot_can_read_group,
    connect_added_group,
    connect_added_group_to_address,
    deactivate_bot_group,
    eligible_admin_group,
    eligible_admin_groups,
    get_address_catalog,
    pending_for_actor,
    pending_for_address,
    register_bot_group,
)
from chat_link.handlers.links import get_request_by_token
from chat_link.handlers.registry import connected_admin_groups
from chat_link.handlers.residence_selection import resolve_residence
from chat_link.models import ChatLinkStatus
from project.bot_media import other_messages_image
from project.bot_screens import send_screen, sent_mid
from project.database import session_scope
from project.docs_links import docs_html
from project.logging_setup import get_logger
from project.max_events import extract_chat_id, extract_sender, is_private_chat_event
from user_chat.handlers import (
    bind_known_chat_member,
    detach_chat,
    get_chat,
    list_chat_addresses,
    remove_user_from_chat,
    set_member_address,
)

logger = get_logger(__name__)

_GROUP_CONNECT_TASKS: dict[int, asyncio.Task[None]] = {}
_GROUP_ADMIN_CHECK_ATTEMPTS = 120
_GROUP_ADMIN_CHECK_DELAY = 2.0


def _callback_payload(event: Any) -> str:
    callback = getattr(event, "callback", None)
    return str(getattr(callback, "payload", "") or "")


def _callback_user_id(event: Any) -> int:
    return int(event.callback.user.user_id)


def _screen_mid(event: Any) -> str | None:
    message = getattr(event, "message", None)
    body = getattr(message, "body", None)
    mid = getattr(body, "mid", None)
    return str(mid) if mid else None


async def _ack_callback(event: Any, *, notification: str = "…") -> None:
    """Снять spinner кнопки. MAX требует message или notification в /answers."""
    ack = getattr(event, "ack", None)
    if not callable(ack):
        return
    try:
        await ack(notification=notification)
    except Exception:
        logger.debug("Не удалось быстро подтвердить callback", exc_info=True)


def _significant_prefix(value: str) -> str:
    return "".join(ch for ch in normalize_ui_text(value) if ch.isalnum())


def _filter_prefix(values: list[str], prefix: str | None) -> list[str]:
    if not prefix:
        return values
    return [value for value in values if _significant_prefix(value).startswith(prefix)]


def _page_text(title: str, page: int, pages: int) -> str:
    # Номер страницы уже виден в единой строке навигации клавиатуры.
    return title


def _house_labels(rows: list[Any]) -> list[str]:
    """Дом остаётся короткой кнопкой; locality добавляется только при реальном дубле номера."""
    counts: dict[str, int] = {}
    for row in rows:
        key = normalize_ui_text(row.house)
        counts[key] = counts.get(key, 0) + 1
    labels: list[str] = []
    for row in rows:
        label = row.house
        if counts.get(normalize_ui_text(row.house), 0) > 1:
            locality = row.district or row.city
            if locality:
                label = f"{row.house} · {locality}"
        labels.append(label)
    return labels


async def _show_welcome(event: Any, context: Any, bot: Any) -> None:
    """Вернуть callback-flow на основной welcome-screen бота."""
    max_user_id = _callback_user_id(event)
    with session_scope() as session:
        user = get_user_by_max_id(session, max_user_id)
    if user is None:
        return

    data = await context.get_data()
    target_chat_id = data.get("target_chat_id")
    resident_chat_id = data.get("resident_chat_id")
    flow_mid = _screen_mid(event) or data.get("flow_mid")
    await context.set_state(None)
    clean_data = {}
    if flow_mid:
        clean_data["flow_mid"] = flow_mid
    if target_chat_id is not None:
        clean_data["target_chat_id"] = target_chat_id
    if resident_chat_id is not None:
        clean_data["resident_chat_id"] = resident_chat_id
    if data.get("first_welcome_mid"):
        clean_data["first_welcome_mid"] = data["first_welcome_mid"]
    await context.set_data(clean_data)

    show_events = await asyncio.to_thread(user_can_see_events, max_user_id)
    kwargs = {
        "text": ADDRESS_PICKER_TEXT,
        "attachments": [],
        "format": Format.HTML,
        "notify": False,
    }
    keyboard = build_welcome_keyboard(
        bot,
        show_events=show_events,
        binding_group=target_chat_id is not None,
        choosing_residence=resident_chat_id is not None,
        can_choose_address=True,
    )
    if keyboard is not None:
        kwargs["attachments"].append(keyboard)
    if flow_mid:
        await _ack_callback(event)
        await bot.edit_message(flow_mid, **kwargs)
    else:
        await event.edit(**kwargs)


async def _show_manage_list(event: Any, context: Any, bot: Any) -> None:
    """Вернуться в «Мои адреса» после chat_link:start:manage."""
    max_user_id = _callback_user_id(event)
    await context.set_state(None)
    data = await context.get_data()
    clean: dict[str, Any] = {}
    mid = _screen_mid(event) or data.get("flow_mid")
    if mid:
        clean["flow_mid"] = mid
    await context.set_data(clean)
    text, keyboard = await asyncio.to_thread(build_manage_list_view, max_user_id)
    kwargs = {
        "text": text,
        "attachments": [other_messages_image(bot), keyboard],
        "format": Format.HTML,
        "notify": False,
    }
    if mid:
        await _ack_callback(event)
        await bot.edit_message(mid, **kwargs)
    else:
        await event.edit(**kwargs)


async def _show_chat_list(event: Any, context: Any, bot: Any) -> None:
    """Назад из выбора адреса для определённой группы."""
    max_user_id = _callback_user_id(event)
    await context.set_state(None)
    data = await context.get_data()
    mid = _screen_mid(event) or data.get("flow_mid")
    await context.set_data({"flow_mid": mid} if mid else {})
    try:
        with session_scope() as session:
            groups = await connected_admin_groups(bot, session, max_user_id=max_user_id)
        text, keyboard = chat_list_view(groups)
    except Exception:
        logger.exception("Не удалось открыть список управляемых чатов")
        text, keyboard = chat_list_view([])
        text = "Не удалось проверить чаты через MAX. Попробуйте ещё раз позже."
    kwargs = {
        "text": text,
        "attachments": [other_messages_image(bot), keyboard],
        "format": Format.HTML,
        "notify": False,
    }
    if mid:
        await _ack_callback(event)
        await bot.edit_message(mid, **kwargs)
    else:
        await event.edit(**kwargs)


def _preserve_flow_flags(data: dict[str, Any]) -> dict[str, Any]:
    """Сохранить режимы bind/resident/manage при смене шага picker-а."""
    keep: dict[str, Any] = {}
    for key in ("target_chat_id", "resident_chat_id", "first_welcome_mid"):
        if data.get(key) is not None:
            keep[key] = data[key]
    if data.get("from_manage"):
        keep["from_manage"] = True
    if data.get("from_chats"):
        keep["from_chats"] = True
    return keep


async def _show_methods(event: Any, context: Any, bot: Any) -> None:
    await context.set_state(ChatLinkStates.choosing)
    mid = _screen_mid(event)
    if mid:
        await context.update_data(flow_mid=mid)
    data = await context.get_data()
    target_chat_id = data.get("target_chat_id")
    resident_chat_id = data.get("resident_chat_id")
    from_manage = bool(data.get("from_manage"))
    from_chats = bool(data.get("from_chats"))
    text = (
        "Выберите адрес, который нужно добавить к чату. Можно будет добавить и другие дома двора."
        if target_chat_id is not None
        else ADDRESS_PICKER_TEXT
    )
    if target_chat_id is not None:
        text = f"{text}\n\n{docs_html('Как выбрать адрес и подключить чат', page='chat-link')}"
    kwargs = {
        "text": text,
        "attachments": [
            method_keyboard(
                bot,
                target_chat_id=target_chat_id,
                resident_chat_id=resident_chat_id,
                from_manage=from_manage,
                from_chats=from_chats,
            )
        ],
        "notify": False,
        "format": Format.HTML,
    }
    if mid:
        # Редактируем и первое welcome — иначе остаётся живая кнопка «Выбрать адрес».
        await _ack_callback(event)
        await bot.edit_message(mid, **kwargs)
        if mid == data.get("first_welcome_mid"):
            await context.update_data(first_welcome_mid=None)
    else:
        await event.edit(**kwargs)


async def _show_city(event: Any, context: Any, page: int = 0) -> None:
    data = await context.get_data()
    postal = data.get("postal_code")
    values = get_address_catalog().cities(postal_code=postal)
    back = "manage" if data.get("from_manage") else "root"
    markup, page, pages = list_keyboard(values, kind="city", page=page, back=back)
    await event.edit(
        text=_page_text("Выберите город", page, pages),
        attachments=[markup],
        notify=False,
    )


async def _show_district(event: Any, context: Any, page: int = 0) -> None:
    data = await context.get_data()
    values = get_address_catalog().districts(data["city"], postal_code=data.get("postal_code"))
    markup, page, pages = list_keyboard(values, kind="district", page=page, back="city")
    await event.edit(
        text=_page_text(f"{data['city']} → выберите район", page, pages),
        attachments=[markup],
        notify=False,
    )


async def _show_street(event: Any, context: Any, page: int = 0) -> None:
    data = await context.get_data()
    values = get_address_catalog().streets(
        data["city"], data["district"], postal_code=data.get("postal_code")
    )
    prefix = data.get("street_prefix") or ""
    values = _filter_prefix(values, prefix)
    if len(values) > 72:
        groups = prefix_groups(values, base_prefix=prefix)
        back = "street_root" if prefix else "district"
        markup, page, pages = list_keyboard(groups, kind="prefix", page=page, back=back)
        await event.edit(
            text=_page_text(
                f"{data['city']} → {data['district']}\nСузьте улицы по началу названия",
                page,
                pages,
            ),
            attachments=[markup],
            notify=False,
        )
        return
    markup, page, pages = list_keyboard(
        values,
        kind="street",
        page=page,
        back="street_root" if data.get("street_prefix") else "district",
    )
    title = f"{data['city']} → {data['district']} → выберите улицу"
    if data.get("street_prefix"):
        title += f"\nФильтр: {data['street_prefix']}"
    await event.edit(text=_page_text(title, page, pages), attachments=[markup], notify=False)


async def _show_house(event: Any, context: Any, page: int = 0) -> None:
    data = await context.get_data()
    rows = get_address_catalog().houses(
        data["city"],
        data["district"],
        data["street"],
        postal_code=data.get("postal_code"),
    )
    labels = _house_labels(rows)
    markup, page, pages = list_keyboard(labels, kind="house", page=page, back="street")
    await event.edit(
        text=_page_text(
            f"{data['city']} → {data['district']} → {data['street']}\nВыберите дом",
            page,
            pages,
        ),
        attachments=[markup],
        notify=False,
    )


async def _show_postal_street(event: Any, context: Any, page: int = 0) -> None:
    data = await context.get_data()
    postal = data["postal_code"]
    values = get_address_catalog().postal_streets(postal)
    back = "manage" if data.get("from_manage") else "root"
    markup, page, pages = list_keyboard(
        values,
        kind="postal_street",
        page=page,
        back=back,
    )
    await event.edit(
        text=_page_text(f"Индекс {postal} → выберите улицу", page, pages),
        attachments=[markup],
        notify=False,
    )


async def _show_postal_house(event: Any, context: Any, page: int = 0) -> None:
    data = await context.get_data()
    postal = data["postal_code"]
    rows = get_address_catalog().postal_houses(postal, data["street"])
    labels = _house_labels(rows)
    markup, page, pages = list_keyboard(
        labels,
        kind="postal_house",
        page=page,
        back="postal_street",
    )
    await event.edit(
        text=_page_text(
            f"Индекс {postal} → {data['street']}\nВыберите дом",
            page,
            pages,
        ),
        attachments=[markup],
        notify=False,
    )


async def _complete_with_home(
    event: Any, bot: Any, max_user_id: int, *, notice: str | None = None
) -> None:
    """Один экран: заменить текущее сообщение на главную (без второго send)."""
    try:
        with session_scope() as session:
            if await edit_to_home(bot, event, session, max_user_id, notice=notice):
                return
            await send_home(bot, session, max_user_id, notice=notice)
    except Exception:
        logger.exception("Не удалось показать главную после выбора дома в боте")


# Совместимость со старыми тестами.


async def _send_home_after_native_selection(
    bot: Any, max_user_id: int, *, notice: str | None = None
) -> None:
    """Fallback без callback-event (тесты / старые вызовы)."""
    try:
        with session_scope() as session:
            await send_home(bot, session, max_user_id, notice=notice)
    except Exception:
        logger.exception("Не удалось отправить главную после выбора дома в боте")


async def _finish_address(event: Any, context: Any, bot: Any, address_id: int) -> None:
    user_id = _callback_user_id(event)
    index = get_address_catalog()
    address = index.get(address_id)
    if address is None:
        await event.ack(notification="Адрес больше не доступен. Начните выбор заново.")
        return

    data = await context.get_data()
    target_chat_id = data.get("target_chat_id")
    resident_chat_id = data.get("resident_chat_id")
    if resident_chat_id is not None:
        await _finish_residence(
            event, context, bot, address_id, resident_chat_id=int(resident_chat_id)
        )
        return
    if target_chat_id is not None:
        with session_scope() as session:
            outcome = await connect_added_group_to_address(
                bot,
                session,
                chat_id=int(target_chat_id),
                admin_max_user_id=user_id,
                address_id=address_id,
            )
        if not outcome.connected:
            await event.edit(
                text=f"Не удалось привязать чат.\n\n{outcome.message or 'Попробуйте ещё раз.'}",
                attachments=[
                    method_keyboard(
                        bot,
                        target_chat_id=int(target_chat_id),
                        from_manage=bool(data.get("from_manage")),
                    )
                ],
                notify=False,
            )
            return

        greeting_failed = False
        try:
            await announce_connected_group(
                bot,
                int(target_chat_id),
                requester_added=outcome.requester_added,
                address_text=address.address_text,
                additional=outcome.message is not None,
                new_message=True,
            )
        except Exception:
            logger.exception("Адрес сохранён, но приветствие не отправлено в групповой чат")
            greeting_failed = True
        await context.set_data({})
        await _complete_with_home(
            event,
            bot,
            user_id,
            notice=(
                f"✅ Чат привязан к адресу: {address.address_text}. "
                "Добавить ещё дом можно в «Администрирование чатов»."
                + (
                    "\n⚠️ Приветствие не удалось отправить в группу. Попробуйте привязку ещё раз."
                    if greeting_failed
                    else ""
                )
            ),
        )
        return

    await _finish_residence(event, context, bot, address_id)


async def _finish_residence(
    event: Any,
    context: Any,
    bot: Any,
    address_id: int,
    *,
    resident_chat_id: int | None = None,
) -> None:
    """Одинаковая проверка из picker-а и из кнопки повторной проверки."""
    user_id = _callback_user_id(event)
    address = get_address_catalog().get(address_id)
    if address is None:
        await event.ack(notification="Адрес больше не доступен. Выберите адрес заново.")
        return
    try:
        with session_scope() as session:
            if resident_chat_id is not None:
                member = await bind_existing_chat_member(
                    bot, session, chat_id=resident_chat_id, max_user_id=user_id
                )
                if member:
                    set_member_address(
                        session, resident_chat_id, max_user_id=user_id, address_id=address_id
                    )
                    set_personal_address(session, max_user_id=user_id, address_id=address_id)
                else:
                    if not any(
                        item.id == address_id
                        for item in list_chat_addresses(session, resident_chat_id)
                    ):
                        raise ValueError("Выбранный адрес не привязан к этому чату")
                    remove_user_from_chat(session, resident_chat_id, max_user_id=user_id)
                mode = "personal_address" if member else "not_member"
                token = None
            else:
                outcome = await resolve_residence(
                    bot, session, max_user_id=user_id, address_id=address_id
                )
                mode, token = outcome.mode, outcome.token
    except ValueError as exc:
        await event.ack(notification=str(exc))
        return
    except Exception:
        logger.exception("Не удалось проверить выбранный дом в MAX")
        await event.edit(
            text="Не удалось проверить адрес через MAX. Попробуйте позже.",
            attachments=[],
            notify=False,
        )
        return
    await context.update_data(address_id=address_id)
    if mode == "not_member":
        await event.edit(
            text=residence_wait_text(address.address_text),
            attachments=[
                residence_result_keyboard(
                    address_id, member=False, resident_chat_id=resident_chat_id
                )
            ],
            notify=False,
            format=Format.HTML,
        )
        return
    if mode == "no_chat":
        await context.update_data(link_token=token)
        await _show_resident_setup(event, context, bot)
        return
    await context.set_data({})
    await event.edit(
        text=residence_success_text(address.address_text),
        attachments=[residence_result_keyboard(address_id, member=True)],
        notify=False,
        format=Format.HTML,
    )


async def _show_resident_setup(
    event: Any, context: Any, bot: Any, *, address_id: int | None = None
) -> None:
    data = await context.get_data()
    if address_id is None:
        address_id = data.get("address_id")
    token = data.get("link_token") if data.get("address_id") == address_id else None
    if address_id is not None and not token:
        with session_scope() as session:
            request = pending_for_address(
                session, max_user_id=_callback_user_id(event), address_id=address_id
            )
        token = request.token if request is not None else None
    address = get_address_catalog().get(address_id) if address_id is not None else None
    if address is None or not token:
        await event.edit(
            text="Сессия выбора адреса устарела. Выберите адрес ещё раз.",
            attachments=[method_keyboard(bot, target_chat_id=data.get("target_chat_id"))],
            notify=False,
        )
        return

    username = getattr(getattr(bot, "me", None), "username", None)
    admin_link = create_start_link(username, f"chat_admin_{token}") if username else None
    await context.update_data(address_id=address_id, link_token=token)
    text = no_chat_text(address.address_text)
    if not admin_link:
        text += "\n\nСейчас ссылку для администратора создать не удалось. Попробуйте ещё раз позже."
    await event.edit(
        text=text,
        attachments=[
            setup_keyboard(admin_link, address.address_text, address_id=address_id, token=token)
        ],
        notify=False,
        format=Format.HTML,
    )


async def _show_admin_setup(
    event: Any, context: Any, bot: Any, *, address_id: int | None = None, failed: bool = False
) -> None:
    data = await context.get_data()
    if address_id is None:
        address_id = data.get("address_id")
    address = get_address_catalog().get(address_id) if address_id is not None else None
    if address is None:
        await event.edit(
            text="Сессия выбора адреса устарела. Выберите адрес ещё раз.",
            attachments=[method_keyboard(bot, target_chat_id=data.get("target_chat_id"))],
            notify=False,
        )
        return

    await context.update_data(address_id=address_id)
    if not failed:
        try:
            with session_scope() as session:
                groups = await eligible_admin_groups(
                    bot, session, max_user_id=_callback_user_id(event)
                )
        except Exception:
            logger.exception("Не удалось проверить группы пользователя в MAX")
            await event.edit(
                text="Возникла ошибка во время проверки. Попробуйте ещё раз позже.",
                attachments=[waiting_admin_keyboard(address_id)],
                notify=False,
            )
            return
        if groups:
            await event.edit(
                text="Чаты, к которым можно привязать адрес:",
                attachments=[admin_groups_keyboard(address_id, groups)],
                notify=False,
            )
            return
    await event.edit(
        text=waiting_admin_text(address.address_text, failed=failed),
        attachments=[waiting_admin_keyboard(address_id)],
        notify=False,
        format=Format.HTML,
    )


async def _show_admin_confirm(
    event: Any, context: Any, bot: Any, *, address_id: int, chat_id: int
) -> None:
    address = get_address_catalog().get(address_id)
    if address is None:
        await _ack_callback(event, notification="Адрес не найден, выберите его заново")
        return
    try:
        with session_scope() as session:
            group = await eligible_admin_group(
                bot, session, chat_id=chat_id, max_user_id=_callback_user_id(event)
            )
    except Exception:
        logger.exception("Не удалось перепроверить права на группу")
        await event.edit(
            text="MAX сейчас не отвечает. Повторите проверку позже.",
            attachments=[waiting_admin_keyboard(address_id)],
            notify=False,
        )
        return
    if group is None:
        await _show_admin_setup(event, context, bot, address_id=address_id, failed=True)
        return
    await context.update_data(address_id=address_id, target_chat_id=chat_id)
    await event.edit(
        text=admin_confirm_text(address.address_text, group),
        attachments=[admin_confirm_keyboard(address_id, chat_id)],
        notify=False,
        format=Format.HTML,
    )


async def _confirm_admin_group(
    event: Any, context: Any, bot: Any, *, address_id: int, chat_id: int
) -> None:
    address = get_address_catalog().get(address_id)
    if address is None:
        await _ack_callback(event, notification="Адрес больше не найден")
        return
    try:
        with session_scope() as session:
            group = await eligible_admin_group(
                bot, session, chat_id=chat_id, max_user_id=_callback_user_id(event)
            )
            if group is None:
                outcome = None
            else:
                outcome = await connect_added_group_to_address(
                    bot,
                    session,
                    chat_id=chat_id,
                    admin_max_user_id=_callback_user_id(event),
                    address_id=address_id,
                )
    except Exception:
        logger.exception("Не удалось завершить привязку чата")
        outcome = None
    if outcome is None or not outcome.connected:
        await _show_admin_setup(event, context, bot, address_id=address_id, failed=True)
        return
    greeting_failed = False
    try:
        await announce_connected_group(
            bot,
            chat_id,
            requester_added=outcome.requester_added,
            address_text=address.address_text,
            additional=outcome.message is not None,
            new_message=True,
        )
    except Exception:
        logger.exception("Привязка сохранена, но приветствие не отправлено в групповой чат")
        greeting_failed = True
    await context.set_data({})
    await event.edit(
        text=(
            f"✅ Адрес {address.address_text} успешно привязан к чату."
            + (
                "\n⚠️ Приветствие не удалось отправить в группу. Попробуйте привязку ещё раз."
                if greeting_failed
                else ""
            )
        ),
        attachments=[admin_success_keyboard()],
        notify=False,
    )


async def _finish_added_group_when_ready(
    bot: Any,
    *,
    chat_id: int,
    actor_max_user_id: int,
    attempts: int = _GROUP_ADMIN_CHECK_ATTEMPTS,
    delay: float = _GROUP_ADMIN_CHECK_DELAY,
) -> None:
    """Дождаться admin+read_all_messages и завершить привязку без `/connect`."""
    for attempt in range(attempts):
        try:
            if await bot_can_read_group(bot, chat_id):
                with session_scope() as session:
                    outcome = await connect_added_group(
                        bot,
                        session,
                        chat_id=chat_id,
                        actor_max_user_id=actor_max_user_id,
                    )
                if not outcome.connected:
                    # Нет старой заявки — это нормальный новый flow: адрес будет выбран
                    # после добавления бота через кнопку в групповом чате.
                    if not outcome.message:
                        return
                    await bot.send_message(chat_id=chat_id, text=outcome.message)
                    return

                with session_scope() as session:
                    connected_chat = get_chat(session, chat_id)
                connected_address = (
                    get_address_catalog().get(connected_chat.address_id)
                    if connected_chat is not None
                    else None
                )
                await announce_connected_group(
                    bot,
                    chat_id,
                    requester_added=outcome.requester_added,
                    address_text=(
                        connected_address.address_text
                        if connected_address is not None
                        else "адрес не найден в справочнике — сообщите администратору"
                    ),
                    new_message=True,
                )
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug(
                "Групповой чат пока не готов к автопривязке (chat_id=%s, attempt=%s): %s",
                chat_id,
                attempt + 1,
                exc,
            )

        if attempt + 1 < attempts:
            await asyncio.sleep(delay)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Не удалось завершить подключение автоматически. Проверьте, что бот назначен "
                "администратором и у него включено право «Читать все сообщения». "
                "После этого удалите и снова добавьте бота в чат."
            ),
        )
    except Exception:
        logger.exception("Не удалось отправить подсказку о правах бота", extra={"chat_id": chat_id})


def _schedule_added_group_connect(bot: Any, *, chat_id: int, actor_max_user_id: int) -> None:
    previous = _GROUP_CONNECT_TASKS.pop(chat_id, None)
    if previous is not None and not previous.done():
        previous.cancel()

    task = asyncio.create_task(
        _finish_added_group_when_ready(
            bot,
            chat_id=chat_id,
            actor_max_user_id=actor_max_user_id,
        )
    )
    _GROUP_CONNECT_TASKS[chat_id] = task

    def _forget(done: asyncio.Task[None]) -> None:
        if _GROUP_CONNECT_TASKS.get(chat_id) is done:
            _GROUP_CONNECT_TASKS.pop(chat_id, None)
        if done.cancelled():
            return
        error = done.exception()
        if error is not None:
            logger.error(
                "Фоновая автопривязка группового чата завершилась ошибкой",
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(_forget)


def register_chat_link_commands(dp: Any, bot: Any) -> None:
    @dp.message_callback()
    async def on_callback(event: Any, context: Any) -> None:
        payload = _callback_payload(event)
        if not payload.startswith("cl:") and not payload.startswith("chat_link:start"):
            return
        if not is_private_chat_event(event):
            await _ack_callback(event, notification="Продолжите в личном чате с ботом")
            return
        if payload.startswith("chat_link:start"):
            from_manage = payload == "chat_link:start:manage"
            from_admin_menu = payload == "chat_link:start:admin"
            from_chats = payload.startswith("chat_link:start:chat:")
            current = await context.get_data()
            flags = _preserve_flow_flags(current)
            # Новый старт не наследует режим привязки от предыдущего выбора.
            flags.pop("target_chat_id", None)
            flags.pop("resident_chat_id", None)
            flags.pop("from_manage", None)
            flags.pop("from_chats", None)
            flags["from_manage"] = from_manage
            if from_admin_menu:
                flags["from_chats"] = True
            if from_chats:
                try:
                    chat_id = int(payload.rsplit(":", 1)[1])
                    with session_scope() as session:
                        candidate = await eligible_admin_group(
                            bot,
                            session,
                            chat_id=chat_id,
                            max_user_id=_callback_user_id(event),
                        )
                        active = get_chat(session, chat_id)
                    if candidate is None or active is None or active.chat_type != "chat":
                        await _ack_callback(event, notification="Чат больше недоступен")
                        return
                except Exception:
                    logger.exception("Не удалось проверить чат перед добавлением адреса")
                    await _ack_callback(event, notification="Не удалось проверить чат")
                    return
                flags["target_chat_id"] = chat_id
                flags["from_chats"] = True
            mid = _screen_mid(event)
            if mid:
                flags["flow_mid"] = mid
            await context.set_data(flags)
            await _show_methods(event, context, bot)
            return
        if payload.startswith("cl:invite:"):
            parts = payload.split(":")
            if len(parts) != 4 or not parts[3].isdigit():
                await _ack_callback(event, notification="Некорректное приглашение")
                return
            token, address_id = parts[2], int(parts[3])
            with session_scope() as session:
                request = get_request_by_token(session, token)
                user = get_user_by_max_id(session, _callback_user_id(event))
            address = get_address_catalog().get(address_id)
            if (
                request is None
                or user is None
                or request.requester_user_id != user.id
                or request.address_id != address_id
                or request.status != ChatLinkStatus.WAITING_GROUP
                or address is None
            ):
                await _ack_callback(event, notification="Приглашение устарело")
                return
            username = getattr(getattr(bot, "me", None), "username", None)
            if not username:
                await _ack_callback(event, notification="Не удалось создать ссылку")
                return
            text = invitation_text(
                address.address_text, create_start_link(username, f"chat_admin_{token}")
            )
            await event.edit(
                text=invitation_preview(text),
                attachments=[invitation_keyboard(address_id=address_id, text=text)],
                format=Format.HTML,
                notify=False,
            )
            return
        if payload == "cl:admin:home":
            await context.set_data({})
            await _complete_with_home(event, bot, _callback_user_id(event))
            return
        if payload.startswith("cl:admin:pick:") or payload.startswith("cl:admin:confirm:"):
            parts = payload.split(":")
            if len(parts) != 5:
                await _ack_callback(event, notification="Некорректная кнопка")
                return
            try:
                address_id, chat_id = int(parts[3]), int(parts[4])
            except ValueError:
                await _ack_callback(event, notification="Некорректная кнопка")
                return
            if parts[2] == "pick":
                await _show_admin_confirm(
                    event, context, bot, address_id=address_id, chat_id=chat_id
                )
            else:
                await _confirm_admin_group(
                    event, context, bot, address_id=address_id, chat_id=chat_id
                )
            return
        if payload.startswith("cl:admin:help") or payload.startswith("cl:admin:retry:"):
            parts = payload.split(":")
            if len(parts) not in (3, 4) or (len(parts) == 4 and not parts[3].isdigit()):
                await _ack_callback(event, notification="Некорректная кнопка")
                return
            await _show_admin_setup(
                event, context, bot, address_id=int(parts[3]) if len(parts) == 4 else None
            )
            return
        if payload.startswith("cl:admin:back:"):
            parts = payload.split(":")
            if len(parts) != 4 or not parts[3].isdigit():
                await _ack_callback(event, notification="Некорректная кнопка")
                return
            await _show_resident_setup(event, context, bot, address_id=int(parts[3]))
            return
        if payload == "cl:admin:user":
            await _show_resident_setup(event, context, bot)
            return
        if payload == "cl:noop":
            await _ack_callback(event)
            return
        if payload == "cl:residence:back":
            await _show_methods(event, context, bot)
            return
        if payload.startswith("cl:residence:retry:"):
            parts = payload.split(":")
            try:
                if len(parts) not in (4, 5):
                    raise ValueError("Некорректная кнопка")
                address_id = int(parts[3])
                resident_chat_id = int(parts[4]) if len(parts) == 5 else None
                if address_id <= 0:
                    raise ValueError("Некорректный адрес")
            except ValueError:
                await _ack_callback(event, notification="Некорректная кнопка")
                return
            await _finish_residence(
                event, context, bot, address_id, resident_chat_id=resident_chat_id
            )
            return
        parts = payload.split(":")
        if payload == "cl:method:native":
            current = await context.get_data()
            data = _preserve_flow_flags(current)
            mid = _screen_mid(event)
            if mid:
                data["flow_mid"] = mid
            await context.set_data(data)
            await context.set_state(ChatLinkStates.choosing)
            await _show_city(event, context)
            return

        if payload == "cl:method:postal":
            current = await context.get_data()
            from_manage = bool(current.get("from_manage"))
            await context.set_state(ChatLinkStates.postal)
            mid = _screen_mid(event)
            if mid:
                await context.update_data(flow_mid=mid)
            await event.edit(
                text=(
                    "Введите шестизначный почтовый индекс. Он только сузит список адресов.\n\n"
                    f"{docs_html('Как выбрать адрес', page='chat-link')}"
                ),
                attachments=[postal_input_keyboard(from_manage=from_manage)],
                notify=False,
                format=Format.HTML,
            )
            return

        if parts[:2] == ["cl", "back"]:
            target = parts[2]
            if target == "welcome":
                await _show_welcome(event, context, bot)
            elif target == "manage":
                await _show_manage_list(event, context, bot)
            elif target == "chats":
                await _show_chat_list(event, context, bot)
            elif target == "root":
                await _show_methods(event, context, bot)
            elif target == "city":
                await _show_city(event, context)
            elif target == "district":
                await _show_district(event, context)
            elif target == "street":
                await _show_street(event, context)
            elif target == "street_root":
                await context.update_data(street_prefix=None)
                await _show_street(event, context)
            elif target == "postal":
                data = await context.get_data()
                await context.set_state(ChatLinkStates.postal)
                await event.edit(
                    text=(
                        "Введите шестизначный почтовый индекс. Он только сузит список адресов.\n\n"
                        f"{docs_html('Как выбрать адрес', page='chat-link')}"
                    ),
                    attachments=[postal_input_keyboard(from_manage=bool(data.get("from_manage")))],
                    notify=False,
                    format=Format.HTML,
                )
            elif target == "postal_street":
                await _show_postal_street(event, context)
            return

        if len(parts) == 4 and parts[2] == "page":
            kind, page = parts[1], int(parts[3])
            if kind == "city":
                await _show_city(event, context, page)
            elif kind == "district":
                await _show_district(event, context, page)
            elif kind in {"street", "prefix"}:
                await _show_street(event, context, page)
            elif kind == "house":
                await _show_house(event, context, page)
            elif kind == "postal_street":
                await _show_postal_street(event, context, page)
            elif kind == "postal_house":
                await _show_postal_house(event, context, page)
            return

        if len(parts) == 4 and parts[2] == "pick":
            kind, idx = parts[1], int(parts[3])
            data = await context.get_data()
            postal = data.get("postal_code")
            index = get_address_catalog()
            if kind == "city":
                values = index.cities(postal_code=postal)
                await context.update_data(city=values[idx], street_prefix=None)
                await _show_district(event, context)
            elif kind == "district":
                values = index.districts(data["city"], postal_code=postal)
                await context.update_data(district=values[idx], street_prefix=None)
                await _show_street(event, context)
            elif kind == "prefix":
                values = index.streets(data["city"], data["district"], postal_code=postal)
                prefix = data.get("street_prefix") or ""
                values = _filter_prefix(values, prefix)
                groups = prefix_groups(values, base_prefix=prefix)
                await context.update_data(street_prefix=groups[idx])
                await _show_street(event, context)
            elif kind == "street":
                values = index.streets(data["city"], data["district"], postal_code=postal)
                values = _filter_prefix(values, data.get("street_prefix"))
                await context.update_data(street=values[idx])
                await _show_house(event, context)
            elif kind == "house":
                rows = index.houses(
                    data["city"],
                    data["district"],
                    data["street"],
                    postal_code=postal,
                )
                await _finish_address(event, context, bot, rows[idx].id)
            elif kind == "postal_street":
                values = index.postal_streets(data["postal_code"])
                await context.update_data(street=values[idx])
                await _show_postal_house(event, context)
            elif kind == "postal_house":
                rows = index.postal_houses(data["postal_code"], data["street"])
                await _finish_address(event, context, bot, rows[idx].id)
            return

        # Неизвестный chat_link callback всё равно подтверждаем, чтобы снять spinner.
        # Ветви выше используют event.edit()/event.ack() как единственный callback-ответ.
        await _ack_callback(event)

    async def _reply_to_postal_input(
        event: Any, context: Any, data: dict[str, Any], *, text: str, attachments: list[Any]
    ) -> str | None:
        """Текст пользователя всегда получает ответ НИЖЕ него, а не edit сверху."""
        sender = extract_sender(event)
        chat_id = extract_chat_id(event)
        user_id = getattr(sender, "user_id", None) or chat_id
        if user_id is None:
            logger.warning("Нет получателя у сообщения с индексом")
            return None
        recipient = {"chat_id": chat_id} if chat_id is not None else {"user_id": user_id}
        result = await send_screen(
            bot,
            int(user_id),
            previous_mid=data.get("flow_mid"),
            **recipient,
            text=text,
            attachments=attachments,
            format=Format.HTML,
        )
        mid = sent_mid(result)
        if mid:
            await context.update_data(flow_mid=mid)
        return mid

    @dp.message_created(F.message.body.text, ChatLinkStates.postal)
    async def on_postal(event: Any, context: Any) -> None:
        if not is_private_chat_event(event):
            return
        body = getattr(event.message, "body", None)
        text = (getattr(body, "text", None) or "").strip()
        data = await context.get_data()
        from_manage = bool(data.get("from_manage"))
        if not (len(text) == 6 and text.isdigit()):
            await _reply_to_postal_input(
                event,
                context,
                data,
                text=(
                    "❗ Ошибка ❗\n\nИндекс должен состоять ровно из 6 цифр. "
                    "Введите индекс ещё раз.\n\n"
                    f"{docs_html('Как выбрать адрес', page='chat-link')}."
                ),
                attachments=[postal_input_keyboard(from_manage=from_manage)],
            )
            return

        streets = get_address_catalog().postal_streets(text)
        if not streets:
            await _reply_to_postal_input(
                event,
                context,
                data,
                text=(
                    "❗ Ошибка ❗\n\nТакого индекса нет в справочнике. "
                    "Введите другой шестизначный индекс.\n\n"
                    f"{docs_html('Как выбрать адрес', page='chat-link')}."
                ),
                attachments=[postal_input_keyboard(from_manage=from_manage)],
            )
            return

        markup, page, pages = list_keyboard(streets, kind="postal_street", page=0, back="postal")
        mid = await _reply_to_postal_input(
            event,
            context,
            data,
            text=_page_text(f"Индекс {text} → выберите улицу", page, pages),
            attachments=[markup],
        )
        if not mid:
            return
        await context.set_state(ChatLinkStates.choosing)
        await context.set_data(
            {
                "flow_mid": mid,
                "postal_code": text,
                **_preserve_flow_flags(data),
            }
        )

    @dp.bot_added()
    async def on_bot_added(event: Any) -> None:
        if getattr(event, "is_channel", False):
            return
        try:
            chat_id = int(event.chat_id)
            actor_id = getattr(getattr(event, "user", None), "user_id", None)
            actor_max_user_id = int(actor_id) if actor_id is not None else None
            with session_scope() as session:
                register_bot_group(
                    session,
                    chat_id,
                    actor_max_user_id=actor_max_user_id,
                    title=getattr(getattr(event, "chat", None), "title", None),
                )
                existing = get_chat(session, chat_id)
                pending = (
                    pending_for_actor(session, actor_max_user_id)
                    if actor_max_user_id is not None
                    else None
                )
            if existing is not None and existing.chat_type == "chat":
                try:
                    if not await bot_can_read_group(bot, chat_id):
                        await announce_group_address_setup(bot, chat_id)
                except Exception:
                    logger.debug(
                        "Не удалось проверить права бота после повторного добавления",
                        exc_info=True,
                    )
                return

            await announce_group_address_setup(bot, chat_id)
            # Оставляем совместимость со старым flow: если заявка уже была создана
            # до добавления бота, она всё ещё сможет завершиться автоматически.
            if (
                actor_max_user_id is not None
                and pending is not None
                and pending.admin_user_id is not None
            ):
                _schedule_added_group_connect(
                    bot,
                    chat_id=chat_id,
                    actor_max_user_id=actor_max_user_id,
                )
        except Exception:
            logger.exception("Не удалось обработать добавление бота в групповой чат")

    @dp.bot_removed()
    async def on_bot_removed(event: Any) -> None:
        if getattr(event, "is_channel", False):
            return
        chat_id = int(event.chat_id)
        task = _GROUP_CONNECT_TASKS.pop(chat_id, None)
        if task is not None and not task.done():
            task.cancel()
        try:
            with session_scope() as session:
                deactivate_bot_group(session, chat_id)
                detached = detach_chat(session, chat_id)
            if detached:
                logger.info("Домовой чат откреплён после bot_removed", extra={"chat_id": chat_id})
        except Exception:
            logger.exception(
                "Не удалось открепить групповой чат после удаления бота",
                extra={"chat_id": chat_id},
            )

    @dp.user_added()
    async def on_user_added(event: Any) -> None:
        # MAX подтверждает фактическое вступление; только после него пишем membership.
        if getattr(event, "is_channel", False):
            return
        chat_id = int(event.chat_id)
        max_user_id = int(event.user.user_id)
        try:
            with session_scope() as session:
                bind_known_chat_member(session, chat_id, max_user_id=max_user_id)
        except ValueError:
            # Неизвестный сервису чат или пользователь: синхронизировать нечего.
            return

    @dp.user_removed()
    async def on_user_removed(event: Any) -> None:
        """Выход из MAX-группы сразу отзывает право на новости её адресов."""
        if getattr(event, "is_channel", False):
            return
        try:
            with session_scope() as session:
                remove_user_from_chat(
                    session, int(event.chat_id), max_user_id=int(event.user.user_id)
                )
        except Exception:
            logger.exception("Не удалось снять членство после user_removed")

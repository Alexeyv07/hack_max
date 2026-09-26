from __future__ import annotations

import asyncio
from typing import Any

from maxapi import F
from maxapi.enums.format import Format
from maxapi.filters.command import Command
from maxapi.types import CallbackButton
from maxapi.utils.deep_linking import create_start_link
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from address.street_catalog import normalize_ui_text
from auth.commands.home import edit_to_home, send_home
from auth.commands.manage_addresses import build_manage_list_view
from auth.commands.start import ADDRESS_PICKER_TEXT, build_welcome_keyboard, user_can_see_events
from auth.handlers import get_user_by_max_id
from auth.handlers.residence import set_personal_address
from chat_link.commands.keyboards import (
    admin_setup_keyboard,
    list_keyboard,
    method_keyboard,
    postal_input_keyboard,
    prefix_groups,
    setup_keyboard,
)
from chat_link.commands.states import ChatLinkStates
from chat_link.handlers import (
    announce_connected_group,
    announce_group_address_setup,
    bind_existing_chat_member,
    bot_can_read_group,
    connect_added_group,
    connect_added_group_to_address,
    connected_group_address,
    connected_group_keyboard,
    get_address_catalog,
    pending_for_actor,
)
from chat_link.handlers.residence_selection import resolve_residence
from project.database import session_scope
from project.docs_links import docs_html
from project.logging_setup import get_logger
from user_chat.handlers import (
    bind_known_chat_member,
    detach_chat,
    get_chat,
    list_chat_addresses,
    remove_chat_address,
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
    """Вернуться в «Управлять адресами» после chat_link:start:manage."""
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
        "attachments": [keyboard],
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
    text = (
        "Выберите адрес, который нужно добавить к чату. Можно будет добавить и другие дома двора."
        if target_chat_id is not None
        else ADDRESS_PICKER_TEXT
    )
    if target_chat_id is not None:
        text = (
            f"{text}\n\n"
            f"Подсказка: {docs_html('как выбрать адрес и подключить чат', page='chat-link')}."
        )
    kwargs = {
        "text": text,
        "attachments": [
            method_keyboard(
                bot,
                target_chat_id=target_chat_id,
                resident_chat_id=resident_chat_id,
                from_manage=from_manage,
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
        try:
            with session_scope() as session:
                if not await bind_existing_chat_member(
                    bot, session, chat_id=int(resident_chat_id), max_user_id=user_id
                ):
                    raise ValueError("Сначала вступите в этот групповой чат.")
                set_member_address(
                    session, int(resident_chat_id), max_user_id=user_id, address_id=address_id
                )
                set_personal_address(session, max_user_id=user_id, address_id=address_id)
        except ValueError as exc:
            await event.edit(
                text=f"Не удалось сохранить адрес.\n\n{exc}",
                attachments=[
                    method_keyboard(
                        bot,
                        resident_chat_id=int(resident_chat_id),
                        from_manage=bool(data.get("from_manage")),
                    )
                ],
                notify=False,
            )
            return
        await context.set_data({})
        await _complete_with_home(
            event,
            bot,
            user_id,
            notice=f"✅ Ваш адрес сохранён: {address.address_text}",
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

        await announce_connected_group(
            bot,
            int(target_chat_id),
            requester_added=outcome.requester_added,
            address_text=address.address_text,
            additional=outcome.message is not None,
        )
        await context.set_data({})
        await _complete_with_home(
            event,
            bot,
            user_id,
            notice=(
                f"✅ Чат привязан к адресу: {address.address_text}. "
                "Добавить ещё дом можно в «Управлять адресами»."
            ),
        )
        return

    # Личный выбор: членство проверяется у чата ИМЕННО выбранного дома.
    try:
        with session_scope() as session:
            outcome = await resolve_residence(
                bot, session, max_user_id=user_id, address_id=address_id
            )
    except Exception:
        logger.exception("Не удалось проверить выбранный дом в MAX")
        await event.edit(
            text="Не удалось проверить адрес через MAX. Попробуйте позже.",
            attachments=[],
            notify=False,
        )
        return
    await context.update_data(address_id=address_id)
    if outcome.mode == "not_member":
        await event.edit(
            text=(
                f"По адресу {address.address_text} уже подключён домовой чат, "
                "но вашего членства в нём не найдено.\n\n"
                "Присоединитесь к домовому чату через приложение «Госуслуги Дом», "
                "затем вернитесь к боту и выберите адрес снова."
            ),
            attachments=[method_keyboard(bot, from_manage=bool(data.get("from_manage")))],
            notify=False,
        )
        return
    if outcome.mode == "no_chat":
        await context.update_data(link_token=outcome.token)
        await _show_resident_setup(event, context, bot)
        return
    await context.set_data({})
    await _complete_with_home(
        event,
        bot,
        user_id,
        notice=f"✅ Ваш адрес сохранён: {address.address_text}",
    )


async def _show_resident_setup(event: Any, context: Any, bot: Any) -> None:
    data = await context.get_data()
    address_id = data.get("address_id")
    token = data.get("link_token")
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
    text = (
        f"Адрес: {address.address_text}\n\n"
        "Для этого дома пока нет подключённого чата.\n\n"
        "Скопируйте пригласительное сообщение и отправьте его администратору "
        "вашего домового чата. Если вы сами администратор, нажмите кнопку ниже.\n\n"
        f"Пошагово: {docs_html('как подключить домовой чат', page='chat-link')}."
    )
    if not admin_link:
        text += "\n\nСейчас ссылку для администратора создать не удалось. Попробуйте ещё раз позже."
    await event.edit(
        text=text,
        attachments=[setup_keyboard(admin_link, address.address_text)],
        notify=False,
        format=Format.HTML,
    )


async def _show_admin_setup(event: Any, context: Any, bot: Any) -> None:
    data = await context.get_data()
    address_id = data.get("address_id")
    address = get_address_catalog().get(address_id) if address_id is not None else None
    if address is None:
        await event.edit(
            text="Сессия выбора адреса устарела. Выберите адрес ещё раз.",
            attachments=[method_keyboard(bot, target_chat_id=data.get("target_chat_id"))],
            notify=False,
        )
        return

    await event.edit(
        text=(
            f"Адрес: {address.address_text}\n\n"
            "Если бот уже есть в вашем чате соседей — повторно добавлять его не нужно. "
            "Напишите в группу команду /address и нажмите "
            "«Добавить адрес чата (админ)». Потом выберите этот дом в личных сообщениях с ботом.\n\n"
            "Если бота в чате ещё нет: добавьте его в группу и сделайте администратором "
            "с правом «Читать все сообщения». После этого можно выбрать первый адрес.\n\n"
            f"Подробная инструкция: {docs_html('подключение чата', page='chat-link')}."
        ),
        attachments=[admin_setup_keyboard()],
        notify=False,
        format=Format.HTML,
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
        if payload.startswith("chat_link:start"):
            from_manage = payload == "chat_link:start:manage"
            current = await context.get_data()
            flags = _preserve_flow_flags(current)
            flags["from_manage"] = from_manage
            mid = _screen_mid(event)
            if mid:
                flags["flow_mid"] = mid
            await context.set_data(flags)
            await _show_methods(event, context, bot)
            return
        # Действия администратора в группе не редактируют главное сообщение
        # до фактического изменения списка адресов.
        if payload.startswith("cl:group:"):
            parts = payload.split(":")
            if len(parts) not in {4, 5} or parts[:2] != ["cl", "group"]:
                await event.ack(notification="Некорректная команда")
                return
            try:
                chat_id = int(parts[3])
                address_id = int(parts[4]) if len(parts) == 5 else None
            except ValueError:
                await event.ack(notification="Некорректная команда")
                return
            if parts[2] not in {"remove", "pick"} or (parts[2] == "pick") != (
                address_id is not None
            ):
                await event.ack(notification="Некорректная команда")
                return
            try:
                member = await bot.get_chat_member(chat_id, _callback_user_id(event))
                if member is None or not (
                    getattr(member, "is_admin", False) or getattr(member, "is_owner", False)
                ):
                    await event.ack(notification="Действие доступно только администратору чата")
                    return
                if not await bot_can_read_group(bot, chat_id):
                    await event.ack(notification="Дайте боту право «Читать все сообщения»")
                    return
                if parts[2] == "remove":
                    with session_scope() as session:
                        addresses = list_chat_addresses(session, chat_id)
                    if len(addresses) <= 1:
                        await event.ack(
                            notification=(
                                "Это единственный адрес. Чтобы убрать его, удалите бота из чата."
                            )
                        )
                        return
                    keyboard = InlineKeyboardBuilder()
                    for address in addresses:
                        keyboard.row(
                            CallbackButton(
                                text=address.address_text[:120],
                                payload=f"cl:group:pick:{chat_id}:{address.id}",
                            )
                        )
                    pick_text = "Какой адрес убрать из этого чата? Нажмите на нужный."
                    mid = _screen_mid(event)
                    await _ack_callback(event)
                    if mid:
                        try:
                            await bot.edit_message(
                                mid,
                                text=pick_text,
                                attachments=[keyboard.as_markup()],
                                notify=False,
                            )
                            return
                        except Exception:
                            logger.debug(
                                "Не удалось edit список адресов на удаление", exc_info=True
                            )
                    await bot.send_message(
                        chat_id=chat_id,
                        text=pick_text,
                        attachments=[keyboard.as_markup()],
                    )
                    return
                with session_scope() as session:
                    removed = remove_chat_address(session, chat_id, address_id)
                if not removed:
                    await event.ack(notification="Этот адрес уже убран")
                    return
                await _ack_callback(event)
                await announce_connected_group(bot, chat_id)
                mid = _screen_mid(event)
                if mid:
                    await bot.edit_message(
                        mid,
                        text=(
                            "Готово: этот адрес больше не привязан к чату. "
                            "Список адресов выше обновлён."
                        ),
                        attachments=[],
                        notify=False,
                    )
                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text="Готово: адрес убран из чата.",
                    )
            except ValueError as exc:
                await event.ack(notification=str(exc))
            except Exception:
                logger.exception("Не удалось изменить адреса группового чата")
                await event.ack(notification="Не удалось изменить адреса, попробуйте позже")
            return
        if payload == "cl:admin:help":
            await _show_admin_setup(event, context, bot)
            return
        if payload == "cl:admin:user":
            await _show_resident_setup(event, context, bot)
            return
        if payload == "cl:noop":
            await _ack_callback(event)
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
                    f"Если не знаете индекс: {docs_html('как выбрать адрес', page='chat-link')}."
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

    @dp.message_created(Command("address"))
    async def on_group_address(event: Any) -> None:
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            recipient = getattr(getattr(event, "message", None), "recipient", None)
            chat_id = getattr(recipient, "chat_id", None)
        if chat_id is None:
            return
        with session_scope() as session:
            address_text = connected_group_address(session, int(chat_id))
        if address_text is None:
            # Тот же экран, что при добавлении бота — иначе инструкция «отправьте /address» тупик.
            await announce_group_address_setup(bot, int(chat_id))
            return
        keyboard = connected_group_keyboard(bot, int(chat_id))
        await bot.send_message(
            chat_id=int(chat_id),
            text=(
                f"🏠 Адреса этого чата:\n{address_text}\n\n"
                "Чтобы подключить ещё один дом, администратор может нажать "
                "«Добавить адрес чата (админ)». Бота повторно добавлять не нужно."
            ),
            attachments=[keyboard] if keyboard is not None else None,
        )

    @dp.message_created(F.message.body.text, ChatLinkStates.postal)
    async def on_postal(event: Any, context: Any) -> None:
        body = getattr(event.message, "body", None)
        text = (getattr(body, "text", None) or "").strip()
        user_mid = getattr(body, "mid", None)
        data = await context.get_data()
        from_manage = bool(data.get("from_manage"))
        if not (len(text) == 6 and text.isdigit()):
            mid = data.get("flow_mid")
            if mid:
                await bot.edit_message(
                    mid,
                    text=(
                        "❗ Ошибка ❗\n\nИндекс должен состоять ровно из 6 цифр. "
                        "Введите индекс ещё раз.\n\n"
                        f"Подсказка: {docs_html('как выбрать адрес', page='chat-link')}."
                    ),
                    attachments=[postal_input_keyboard(from_manage=from_manage)],
                    format=Format.HTML,
                )
            return

        index = get_address_catalog()
        streets = index.postal_streets(text)
        mid = data.get("flow_mid")
        if not streets:
            if mid:
                await bot.edit_message(
                    mid,
                    text=(
                        "❗ Ошибка ❗\n\nТакого индекса нет в справочнике. "
                        "Введите другой шестизначный индекс.\n\n"
                        f"Подсказка: {docs_html('как выбрать адрес', page='chat-link')}."
                    ),
                    attachments=[postal_input_keyboard(from_manage=from_manage)],
                    format=Format.HTML,
                )
            return

        if user_mid:
            try:
                await bot.delete_message(str(user_mid))
            except Exception:
                logger.debug("Не удалось удалить сообщение с индексом", exc_info=True)

        await context.set_state(ChatLinkStates.choosing)
        next_data = {
            "flow_mid": mid,
            "postal_code": text,
            **_preserve_flow_flags(data),
        }
        await context.set_data(next_data)
        if not mid:
            return

        back = "manage" if from_manage else "root"
        markup, page, pages = list_keyboard(
            streets,
            kind="postal_street",
            page=0,
            back=back,
        )
        await bot.edit_message(
            mid,
            text=_page_text(f"Индекс {text} → выберите улицу", page, pages),
            attachments=[markup],
            notify=False,
        )

    @dp.bot_added()
    async def on_bot_added(event: Any) -> None:
        if getattr(event, "is_channel", False):
            return
        try:
            chat_id = int(event.chat_id)
            actor_max_user_id = int(event.user.user_id)
            with session_scope() as session:
                existing = get_chat(session, chat_id)
                pending = pending_for_actor(session, actor_max_user_id)
            if existing is not None and existing.chat_type == "chat":
                return

            if pending is None:
                await announce_group_address_setup(bot, chat_id)
            # Оставляем совместимость со старым flow: если заявка уже была создана
            # до добавления бота, она всё ещё сможет завершиться автоматически.
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

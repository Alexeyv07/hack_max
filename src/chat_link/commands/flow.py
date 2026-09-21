from __future__ import annotations

import asyncio
from typing import Any

from maxapi import F
from maxapi.utils.deep_linking import create_start_link

from address.street_catalog import normalize_ui_text
from chat_link.commands.keyboards import (
    admin_setup_keyboard,
    existing_chats_keyboard,
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
    bot_can_read_group,
    connect_added_group,
    connect_added_group_to_address,
    create_request,
    get_address_catalog,
    mark_waiting_group,
    pending_for_actor,
)
from project.database import session_scope
from project.logging_setup import get_logger
from user_chat.handlers import bind_known_chat_member, detach_chat, get_chat

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


async def _ack_callback(event: Any) -> None:
    """Снять spinner кнопки сразу; тяжёлая работа/редактирование идут после ack."""
    ack = getattr(event, "ack", None)
    if not callable(ack):
        return
    try:
        await ack()
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


async def _show_methods(event: Any, context: Any, bot: Any) -> None:
    await context.set_state(ChatLinkStates.choosing)
    mid = _screen_mid(event)
    if mid:
        await context.update_data(flow_mid=mid)
    data = await context.get_data()
    target_chat_id = data.get("target_chat_id")
    if target_chat_id is None:
        text = (
            "Как хотите указать место жительства?\n\n"
            "Индекс только сужает список домов — он не считается выбранным адресом."
        )
    else:
        text = (
            "Выберите адрес, к которому нужно привязать этот домовой чат.\n\n"
            "Индекс только сужает список домов — он не считается выбранным адресом."
        )
    await event.edit(
        text=text,
        attachments=[method_keyboard(bot, target_chat_id=target_chat_id)],
        notify=False,
    )


async def _show_city(event: Any, context: Any, page: int = 0) -> None:
    data = await context.get_data()
    postal = data.get("postal_code")
    values = get_address_catalog().cities(postal_code=postal)
    markup, page, pages = list_keyboard(values, kind="city", page=page, back="root")
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
    markup, page, pages = list_keyboard(values, kind="street", page=page, back="district")
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
    markup, page, pages = list_keyboard(
        values,
        kind="postal_street",
        page=page,
        back="root",
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


async def _finish_address(event: Any, context: Any, bot: Any, address_id: int) -> None:
    user_id = _callback_user_id(event)
    index = get_address_catalog()
    address = index.get(address_id)
    if address is None:
        await event.ack(notification="Адрес больше не доступен. Начните выбор заново.")
        return

    data = await context.get_data()
    target_chat_id = data.get("target_chat_id")
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
                attachments=[method_keyboard(bot, target_chat_id=int(target_chat_id))],
                notify=False,
            )
            return

        await announce_connected_group(
            bot,
            int(target_chat_id),
            requester_added=outcome.requester_added,
        )
        await context.update_data(address_id=address_id)
        await event.edit(
            text=(
                "✅ Чат успешно привязан к адресу:\n"
                f"{address.address_text}\n\n"
                "Можно вернуться в групповой чат."
            ),
            attachments=[],
            notify=False,
        )
        return

    with session_scope() as session:
        request, chats = create_request(session, max_user_id=user_id, address_id=address_id)
    await context.update_data(address_id=address_id, link_token=request.token)
    if chats:
        linked = [chat for chat in chats if chat.invite_link]
        names_without_link = [chat.title for chat in chats if not chat.invite_link]
        text = (
            f"Для этого дома уже подключён домовой чат:\n{address.address_text}\n\n"
            "Вступите в него по ссылке ниже. После вступления MAX сам пришлёт событие, "
            "и бот привяжет ваш профиль к дому."
        )
        if names_without_link:
            text += (
                "\n\nУ некоторых чатов нет публичной ссылки. Для них попросите "
                "администратора прислать приглашение: " + ", ".join(names_without_link[:3])
            )
        await event.edit(
            text=text,
            attachments=[existing_chats_keyboard(linked or chats)],
            notify=False,
        )
        return
    # В старом mock `chats` мог содержать личный DIALOG. После проверки MAX
    # такая запись не должна оставлять заявку в WAITING_JOIN.
    with session_scope() as session:
        mark_waiting_group(session, token=request.token)
    await _show_resident_setup(event, context, bot)


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
        "Для этого дома пока нет подключённого чата. Если вы обычный житель, "
        "отправьте администратору домового чата ссылку кнопкой ниже. "
        "Когда администратор подключит чат, вы сможете вступить в него и получать события по дому."
    )
    if not admin_link:
        text += "\n\nСейчас ссылку для администратора создать не удалось. Попробуйте ещё раз позже."
    await event.edit(
        text=text,
        attachments=[setup_keyboard(admin_link)],
        notify=False,
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
            "Если вы администратор домового чата, добавьте этого бота в нужный групповой чат, "
            "затем назначьте его администратором с правом «Читать все сообщения». "
            "После этого чат подключится автоматически — дополнительных команд не нужно."
        ),
        attachments=[admin_setup_keyboard()],
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

                await announce_connected_group(
                    bot,
                    chat_id,
                    requester_added=outcome.requester_added,
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
        if not payload.startswith("cl:") and payload != "chat_link:start":
            return
        await _ack_callback(event)
        if payload == "chat_link:start":
            await _show_methods(event, context, bot)
            return
        if payload == "cl:admin:help":
            await _show_admin_setup(event, context, bot)
            return
        if payload == "cl:admin:user":
            await _show_resident_setup(event, context, bot)
            return
        if payload == "cl:noop":
            return

        parts = payload.split(":")
        if payload == "cl:method:native":
            current = await context.get_data()
            data = {"flow_mid": _screen_mid(event)}
            if current.get("target_chat_id") is not None:
                data["target_chat_id"] = current["target_chat_id"]
            await context.set_data(data)
            await context.set_state(ChatLinkStates.choosing)
            await _show_city(event, context)
            return

        if payload == "cl:method:postal":
            await context.set_state(ChatLinkStates.postal)
            mid = _screen_mid(event)
            if mid:
                await context.update_data(flow_mid=mid)
            await event.edit(
                text="Введите шестизначный почтовый индекс. Он только сузит список адресов.",
                attachments=[postal_input_keyboard()],
                notify=False,
            )
            return

        if parts[:2] == ["cl", "back"]:
            target = parts[2]
            if target == "root":
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

    @dp.message_created(F.message.body.text, ChatLinkStates.postal)
    async def on_postal(event: Any, context: Any) -> None:
        body = getattr(event.message, "body", None)
        text = (getattr(body, "text", None) or "").strip()
        if not (len(text) == 6 and text.isdigit()):
            data = await context.get_data()
            mid = data.get("flow_mid")
            if mid:
                await bot.edit_message(
                    mid,
                    text="❗ Ошибка ❗\n\nИндекс должен состоять ровно из 6 цифр. Введите индекс ещё раз.",
                    attachments=[postal_input_keyboard()],
                )
            return

        index = get_address_catalog()
        streets = index.postal_streets(text)
        data = await context.get_data()
        mid = data.get("flow_mid")
        if not streets:
            if mid:
                await bot.edit_message(
                    mid,
                    text="❗ Ошибка ❗\n\nТакого индекса нет в справочнике. Введите другой шестизначный индекс.",
                    attachments=[postal_input_keyboard()],
                )
            return

        await context.set_state(ChatLinkStates.choosing)
        next_data = {
            "flow_mid": mid,
            "postal_code": text,
        }
        if data.get("target_chat_id") is not None:
            next_data["target_chat_id"] = data["target_chat_id"]
        await context.set_data(next_data)
        if not mid:
            return

        markup, page, pages = list_keyboard(
            streets,
            kind="postal_street",
            page=0,
            back="root",
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

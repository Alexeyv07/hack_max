from __future__ import annotations

from typing import Any

from maxapi.enums import ChatType
from maxapi.exceptions.max import MaxApiError
from maxapi.types import CallbackButton, LinkButton
from maxapi.utils.deep_linking import create_start_link
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy.orm import Session

from chat_link.handlers.links import (
    create_request,
    finalize_group,
    get_request_by_token,
    mark_joined,
    pending_for_actor,
)
from chat_link.models import ConnectOutcome, JoinOutcome
from project.bot_media import first_start_image
from project.database import session_scope
from project.docs_links import docs_html
from user_chat.db import ChatRow
from user_chat.handlers import (
    add_chat_address,
    bind_known_chat_member,
    get_chat,
    list_chat_addresses,
    list_chats_by_address,
)
from user_chat.models import Chat


def _permission_names(member: Any) -> set[str]:
    return {
        str(getattr(permission, "value", permission))
        for permission in (getattr(member, "permissions", None) or [])
    }


async def bot_can_read_group(bot: Any, chat_id: int) -> bool:
    """Бот уже админ группы и может получать все сообщения из неё."""
    member = await bot.get_me_from_chat(chat_id)
    is_admin = bool(getattr(member, "is_admin", False) or getattr(member, "is_owner", False))
    return is_admin and "read_all_messages" in _permission_names(member)


async def bind_existing_chat_member(
    bot: Any,
    session: Session,
    *,
    chat_id: int,
    max_user_id: int,
) -> bool:
    """Привязать пользователя только после проверки членства через MAX API.

    Не добавляем человека в MAX-чат и не требуем решения администратора.
    """
    member = await bot.get_chat_member(chat_id, max_user_id)
    if member is None:
        return False
    bind_known_chat_member(session, chat_id, max_user_id=max_user_id)
    return True


async def select_linked_member_residence(
    bot: Any, session: Session, *, max_user_id: int, address_id: int
) -> bool:
    """Совместимость старого вызова; проверяет чат именно выбранного адреса."""
    from chat_link.handlers.residence_selection import resolve_residence

    selection = await resolve_residence(
        bot, session, max_user_id=max_user_id, address_id=address_id
    )
    return selection.mode == "personal_address"


async def bind_referral_member(
    bot: Any,
    session: Session,
    *,
    chat_id: int,
    max_user_id: int,
) -> JoinOutcome:
    """Deep-link связывает профиль только после подтверждения membership через MAX."""
    member = await bot.get_chat_member(chat_id, max_user_id)
    if member is None:
        return JoinOutcome(
            False,
            "Сначала вступите в домовой чат, затем откройте эту ссылку ещё раз.",
        )
    try:
        bind_known_chat_member(session, chat_id, max_user_id=max_user_id)
    except ValueError:
        return JoinOutcome(False, "Этот домовой чат ещё не подключён к сервису.")
    return JoinOutcome(
        True,
        "Членство в чате подтверждено. Укажите свой адрес, чтобы видеть события рядом с домом.",
    )


async def existing_group_chats(bot: Any, chats: list[Chat]) -> list[Chat]:
    """Оставить только реальные групповые MAX-чаты и освежить их метаданные.

    До реальной group integration старый mock мог сохранить личный DIALOG в
    таблицу `chats`. Такие записи нельзя показывать как домовые чаты.
    """
    result: list[Chat] = []
    seen: set[int] = set()
    for stored in chats:
        if stored.chat_id in seen:
            continue
        try:
            remote = await bot.get_chat_by_id(stored.chat_id)
        except MaxApiError as exc:
            if exc.code in {400, 404}:
                continue
            raise
        if getattr(remote, "type", None) != ChatType.CHAT:
            continue
        seen.add(stored.chat_id)
        result.append(
            Chat(
                chat_id=stored.chat_id,
                address_id=stored.address_id,
                title=getattr(remote, "title", None) or stored.title,
                invite_link=getattr(remote, "link", None) or stored.invite_link,
                chat_type="chat",
            )
        )
    return result


async def join_existing_chat(
    bot: Any,
    session: Session,
    *,
    token: str,
    chat_id: int,
    max_user_id: int,
) -> JoinOutcome:
    """Сохранить membership только если пользователь уже вступил в MAX-группу."""
    request = get_request_by_token(session, token)
    chat = get_chat(session, chat_id)
    if request is None or chat is None or chat.address_id != request.address_id:
        return JoinOutcome(False, "Чат не найден для выбранного адреса")

    member = await bot.get_chat_member(chat_id, max_user_id)
    if member is None:
        return JoinOutcome(False, "Вы не состоите в домовом чате, привязанном к выбранному адресу.")

    mark_joined(session, token=token, chat_id=chat_id)
    return JoinOutcome(True, "Членство в домовом чате подтверждено")


async def connect_group_chat(
    bot: Any,
    session: Session,
    *,
    token: str,
    chat_id: int,
    admin_max_user_id: int,
) -> ConnectOutcome:
    """Проверить админа и привязать реальную MAX-группу без auto-add участников."""
    member = await bot.get_chat_member(chat_id, admin_max_user_id)
    if member is None or not (
        getattr(member, "is_admin", False) or getattr(member, "is_owner", False)
    ):
        return ConnectOutcome(
            False,
            chat_id,
            False,
            "Привязать дом к групповому чату может только администратор этого чата.",
        )

    chat = await bot.get_chat_by_id(chat_id)
    try:
        requester_max_id = finalize_group(
            session,
            token=token,
            chat_id=chat_id,
            title=chat.title or "Чат соседей",
            invite_link=chat.link,
            admin_max_user_id=admin_max_user_id,
        )
    except ValueError as exc:
        return ConnectOutcome(False, chat_id, False, str(exc))

    requester_added = requester_max_id == admin_max_user_id

    return ConnectOutcome(True, chat_id, requester_added)


async def connect_added_group(
    bot: Any,
    session: Session,
    *,
    chat_id: int,
    actor_max_user_id: int,
) -> ConnectOutcome:
    """Автоматически связать `bot_added` с активным onboarding пользователя."""
    request = pending_for_actor(session, actor_max_user_id)
    if request is None:
        # Новый flow позволяет сначала добавить бота в группу, а адрес выбрать уже потом.
        # В таком случае bot_added не должен пугать пользователя ошибкой: прямой bind-flow
        # завершит привязку после выбора адреса.
        return ConnectOutcome(False, chat_id, False)
    return await connect_group_chat(
        bot,
        session,
        token=request.token,
        chat_id=chat_id,
        admin_max_user_id=actor_max_user_id,
    )


async def connect_added_group_to_address(
    bot: Any,
    session: Session,
    *,
    chat_id: int,
    admin_max_user_id: int,
    address_id: int,
) -> ConnectOutcome:
    """Привязать уже добавленную MAX-группу к выбранному после этого адресу.

    Администратор выбирает первый или дополнительный адрес для уже добавленной группы.
    """
    if not await bot_can_read_group(bot, chat_id):
        return ConnectOutcome(
            False,
            chat_id,
            False,
            "Сначала назначьте бота администратором и включите право «Читать все сообщения».",
        )

    member = await bot.get_chat_member(chat_id, admin_max_user_id)
    if member is None or not (
        getattr(member, "is_admin", False) or getattr(member, "is_owner", False)
    ):
        return ConnectOutcome(
            False,
            chat_id,
            False,
            "Привязать адрес может только администратор этого группового чата.",
        )

    existing_chat = get_chat(session, chat_id)
    if existing_chat is not None:
        if existing_chat.chat_type == "chat":
            occupied = [
                chat
                for chat in list_chats_by_address(session, address_id)
                if chat.chat_id != chat_id
            ]
            if occupied:
                return ConnectOutcome(
                    False,
                    chat_id,
                    False,
                    "Для этого адреса уже подключён другой домовой чат. Выберите другой адрес.",
                )
            added = add_chat_address(session, chat_id, address_id)
            return ConnectOutcome(
                True,
                chat_id,
                True,
                "Адрес добавлен к чату." if added else "Этот адрес уже добавлен к чату.",
            )
        if existing_chat.address_id != address_id:
            return ConnectOutcome(
                False,
                chat_id,
                False,
                "Этот MAX-чат уже был связан с другим адресом и не может быть перепривязан автоматически.",
            )

    occupied = [
        chat for chat in list_chats_by_address(session, address_id) if chat.chat_id != chat_id
    ]
    if occupied:
        return ConnectOutcome(
            False,
            chat_id,
            False,
            "Для этого адреса уже подключён другой домовой чат. Выберите другой адрес.",
        )

    request, chats = create_request(
        session,
        max_user_id=admin_max_user_id,
        address_id=address_id,
    )
    if chats:
        return ConnectOutcome(
            False,
            chat_id,
            False,
            "Для этого адреса уже подключён другой домовой чат. Выберите другой адрес.",
        )
    return await connect_group_chat(
        bot,
        session,
        token=request.token,
        chat_id=chat_id,
        admin_max_user_id=admin_max_user_id,
    )


def connected_group_address(session: Session, chat_id: int) -> str | None:
    """Все адреса подтверждённой группы для команды /address."""
    addresses = list_chat_addresses(session, chat_id)
    return "\n".join(address.address_text for address in addresses) or None


def _group_link_keyboard(url: str | None, *, text: str) -> Any | None:
    if not url:
        return None
    builder = InlineKeyboardBuilder()
    builder.row(LinkButton(text=text, url=url))
    return builder.as_markup()


async def announce_group_address_setup(bot: Any, chat_id: int) -> None:
    """Подсказать в новой группе, как выбрать адрес уже после добавления бота."""
    username = getattr(getattr(bot, "me", None), "username", None)
    bind_link = create_start_link(username, f"chat_bind_{chat_id}") if username else None
    text = (
        "Бот добавлен в чат. Чтобы подключить этот чат к дому, администратору нужно:\n"
        "1. Назначить бота администратором с правом «Читать все сообщения».\n"
        "2. Нажать «Выбрать адрес» и указать дом. Позже можно добавить другие дома двора.\n\n"
        "Каждый адрес должен быть свободен от привязки к другому чату.\n\n"
        f"Инструкция: {docs_html('как подключить домовой чат', page='chat-link')}."
    )
    if not bind_link:
        text += (
            "\n\nНе удалось создать кнопку выбора адреса. "
            "Откройте бота в личном чате и попробуйте ещё раз."
        )
    keyboard = _group_link_keyboard(bind_link, text="Выбрать адрес")
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboard] if keyboard is not None else None,
        format="html",
    )


async def announce_connected_group(
    bot: Any,
    chat_id: int,
    *,
    requester_added: bool = True,
    address_text: str = "",
    additional: bool = False,
) -> None:
    """Одно закреплённое по смыслу сообщение: обновляем список при изменениях."""
    username = getattr(getattr(bot, "me", None), "username", None)
    referral = create_start_link(username, f"chat_{chat_id}") if username else None
    bind_link = create_start_link(username, f"chat_bind_{chat_id}") if username else None
    with session_scope() as session:
        chat = session.get(ChatRow, chat_id)
        if chat is None or chat.chat_type != "chat":
            return
        addresses = [address.address_text for address in list_chat_addresses(session, chat_id)]
        address_block = "\n".join(f"• {address}" for address in addresses)
        text = (
            "✅ Домовой чат подключён к адресам:\n"
            f"{address_block}\n\n"
            "Проверьте, что адреса указаны верно. Если заметили ошибку, "
            "сообщите администратору чата.\n\n"
            "Чат может объединять несколько домов. Каждый житель должен указать свой адрес, "
            "чтобы видеть события рядом с ним."
        )
        if referral:
            text += "\n\nСоседи могут указать дом кнопкой ниже после вступления в чат."
        if not requester_added:
            text += "\n\nИнициатору нужно вступить в этот чат и нажать «Указать свой адрес» ниже."
        keyboard = _connected_group_keyboard(referral, bind_link, chat_id=chat_id)
        attachments = [first_start_image(bot), *([keyboard] if keyboard is not None else [])]
        if chat.welcome_mid:
            try:
                await bot.edit_message(
                    chat.welcome_mid, text=text, attachments=attachments, notify=False
                )
                return
            except MaxApiError as exc:
                if exc.code not in {400, 404}:
                    raise
                # Сообщение удалено в MAX: создадим новое и запомним его id.
        result = await bot.send_message(chat_id=chat_id, text=text, attachments=attachments)
        body = getattr(getattr(result, "message", None), "body", None)
        mid = getattr(body, "mid", None)
        if mid:
            chat.welcome_mid = str(mid)


def _connected_group_keyboard(
    referral: str | None, bind_link: str | None, *, chat_id: int
) -> Any | None:
    builder = InlineKeyboardBuilder()
    if referral:
        builder.row(LinkButton(text="Указать свой адрес", url=referral))
    if bind_link:
        builder.row(LinkButton(text="Добавить адрес чата (админ)", url=bind_link))
    builder.row(
        CallbackButton(text="Удалить адрес чата (админ)", payload=f"cl:group:remove:{chat_id}")
    )
    return builder.as_markup()


def connected_group_keyboard(bot: Any, chat_id: int) -> Any | None:
    """Повторно показать действия группы, даже если старое сообщение потерялось в чате."""
    username = getattr(getattr(bot, "me", None), "username", None)
    if not username:
        return None
    referral = create_start_link(username, f"chat_{chat_id}")
    bind_link = create_start_link(username, f"chat_bind_{chat_id}")
    return _connected_group_keyboard(referral, bind_link, chat_id=chat_id)

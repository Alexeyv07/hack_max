from __future__ import annotations

from typing import Any

from maxapi.enums import ChatType
from maxapi.exceptions.max import MaxApiError
from maxapi.types import LinkButton
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
from user_chat.handlers import bind_known_chat_member, get_chat, list_chats_by_address
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
        "Домовой чат привязан к вашему профилю. Раздел событий теперь доступен.",
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
        if chat.invite_link:
            return JoinOutcome(
                False,
                "Сначала вступите в домовой чат по ссылке.",
                invite_link=chat.invite_link,
            )
        return JoinOutcome(False, "Сначала вступите в домовой чат через администратора.")

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

    Это основной admin-flow: бот сначала появляется в группе, затем администратор
    открывает deep-link и выбирает дом. Адрес можно занять только одним активным
    домовым чатом.
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
            return ConnectOutcome(
                False,
                chat_id,
                False,
                "Этот MAX-чат уже привязан к адресу.",
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
        "2. Нажать «Выбрать адрес» и указать дом.\n\n"
        "К адресу можно привязать чат, только если другой домовой чат к нему ещё не подключён."
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
    )


async def announce_connected_group(
    bot: Any,
    chat_id: int,
    *,
    requester_added: bool = True,
) -> None:
    """Сообщить группе об успешной привязке и дать соседям referral-кнопку."""
    username = getattr(getattr(bot, "me", None), "username", None)
    referral = create_start_link(username, f"chat_{chat_id}") if username else None
    text = (
        "Чат привязан к дому. Теперь сервис будет использовать сообщения этого домового чата "
        "для событий рядом с жителями."
    )
    if referral:
        text += "\n\nСоседи могут привязать дом кнопкой ниже после того, как вступят в этот чат."
    if not requester_added:
        text += "\n\nИнициатору нужно вступить в этот чат и нажать кнопку «Привязать дом» ниже."
    keyboard = _group_link_keyboard(referral, text="Привязать дом")
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboard] if keyboard is not None else None,
    )

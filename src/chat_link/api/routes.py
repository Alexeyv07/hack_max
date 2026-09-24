from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from maxapi.utils.deep_linking import create_start_link

from auth.commands.home import send_home
from auth.handlers.residence import get_personal_address, set_personal_address
from chat_link.api.schemas import (
    AddressOption,
    AddressSearchResponse,
    AddressSelectRequest,
    AddressSelectResponse,
    PersonalResidenceResponse,
    PostalAddressSearchResponse,
)
from chat_link.handlers import (
    announce_connected_group,
    bind_existing_chat_member,
    bot_can_read_group,
    connect_added_group_to_address,
    get_address_catalog,
)
from chat_link.handlers.residence_selection import resolve_residence
from project.api_deps import DbSession, get_max_user_id
from project.logging_setup import get_logger
from project.max_runtime import get_max_bot
from user_chat.handlers import get_chat, linked_group_ids, remove_chat_address, set_member_address

router = APIRouter(prefix="/chat-link", tags=["chat-link"])
MaxUserId = Annotated[int, Depends(get_max_user_id)]
logger = get_logger(__name__)


async def _send_selected_home(bot, session, max_user_id: int, *, notice: str | None = None) -> None:
    # Сначала сохраняем привязку. Ошибка отправки сообщения не должна откатывать адрес.
    session.commit()
    if bot is None:
        return
    try:
        await send_home(bot, session, max_user_id, notice=notice)
    except Exception:
        logger.exception("Не удалось отправить главную после выбора адреса через WebApp")


def _option(row, score: float | None = None) -> AddressOption:
    return AddressOption(
        id=row.id,
        address_text=row.address_text,
        latitude=row.latitude,
        longitude=row.longitude,
        score=score,
    )


@router.get("/addresses/search", response_model=AddressSearchResponse)
def search_addresses(
    q: Annotated[str, Query(min_length=3, max_length=300)],
) -> AddressSearchResponse:
    items = [_option(row, score) for row, score in get_address_catalog().search(q, limit=12)]
    return AddressSearchResponse(items=items)


@router.get("/addresses/postal", response_model=PostalAddressSearchResponse)
def search_postal_addresses(
    code: Annotated[str, Query(pattern=r"^\d{6}$")],
    q: Annotated[str, Query(max_length=120)] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=30)] = 12,
) -> PostalAddressSearchResponse:
    rows, total = get_address_catalog().postal_addresses(code, query=q, offset=offset, limit=limit)
    return PostalAddressSearchResponse(items=[_option(row) for row in rows], total=total)


@router.get("/addresses/nearest", response_model=AddressSearchResponse)
def nearest_addresses(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> AddressSearchResponse:
    items = [_option(row) for row in get_address_catalog().nearest(lat, lon, limit=5)]
    return AddressSearchResponse(items=items)


@router.get("/residence", response_model=PersonalResidenceResponse)
def get_residence(session: DbSession, max_user_id: MaxUserId) -> PersonalResidenceResponse:
    address = get_personal_address(session, max_user_id)
    if address is not None and not linked_group_ids(session, max_user_id, address_id=address.id):
        address = None
    return PersonalResidenceResponse(address=_option(address) if address is not None else None)


@router.post("/select", response_model=AddressSelectResponse)
async def select_address(
    payload: AddressSelectRequest,
    session: DbSession,
    max_user_id: MaxUserId,
) -> AddressSelectResponse:
    address = get_address_catalog().get(payload.address_id)
    if address is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Адрес не найден")
    bot = get_max_bot()
    if payload.chat_id is not None and payload.resident_chat_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите только один тип привязки"
        )
    if payload.resident_chat_id is not None:
        if bot is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MAX-бот сейчас недоступен")
        try:
            if not await bind_existing_chat_member(
                bot, session, chat_id=payload.resident_chat_id, max_user_id=max_user_id
            ):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Сначала вступите в этот чат")
            set_member_address(
                session,
                payload.resident_chat_id,
                max_user_id=max_user_id,
                address_id=payload.address_id,
            )
            set_personal_address(session, max_user_id=max_user_id, address_id=payload.address_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Не удалось проверить членство через MAX"
            ) from exc
        await _send_selected_home(bot, session, max_user_id)
        return AddressSelectResponse(address=_option(address), mode="resident_address", chats=[])
    if payload.chat_id is not None:
        if bot is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MAX-бот сейчас недоступен")
        try:
            outcome = await connect_added_group_to_address(
                bot,
                session,
                chat_id=payload.chat_id,
                admin_max_user_id=max_user_id,
                address_id=payload.address_id,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        if not outcome.connected:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                outcome.message or "Не удалось привязать чат к адресу",
            )
        session.commit()
        await announce_connected_group(
            bot,
            payload.chat_id,
            requester_added=outcome.requester_added,
            address_text=address.address_text,
            additional=outcome.message is not None,
        )
        await _send_selected_home(bot, session, max_user_id)
        return AddressSelectResponse(
            address=_option(address),
            mode="group_connected",
            chats=[],
        )

    # Любой пользователь может указать дом, но доступ — только после проверки
    # его фактического членства в MAX-чате выбранного адреса.
    if bot is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MAX-бот сейчас недоступен")
    try:
        outcome = await resolve_residence(
            bot, session, max_user_id=max_user_id, address_id=payload.address_id
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Не удалось проверить членство через MAX"
        ) from exc
    if outcome.mode == "personal_address":
        await _send_selected_home(bot, session, max_user_id)
        return AddressSelectResponse(address=_option(address), mode="personal_address", chats=[])

    admin_link = None
    if outcome.mode == "no_chat" and outcome.token:
        username = getattr(getattr(bot, "me", None), "username", None)
        if username:
            admin_link = create_start_link(username, f"chat_admin_{outcome.token}")
    session.commit()
    if outcome.mode == "not_member":
        notice = (
            f"По адресу {address.address_text} уже подключён домовой чат, "
            "но вы не состоите в нём. Присоединитесь через приложение «Госуслуги Дом», "
            "затем повторите выбор адреса."
        )
    else:
        notice = (
            f"По адресу {address.address_text} пока нет подключённого домового чата. "
            "Скопируйте приглашение для администратора или нажмите «Я администратор чата»."
        )
    try:
        await bot.send_message(user_id=max_user_id, text=notice)
    except Exception:
        logger.exception("Не удалось отправить результат выбора адреса в MAX")
    return AddressSelectResponse(
        address=_option(address),
        mode=outcome.mode,
        token=outcome.token,
        admin_link=admin_link,
        chats=[],
    )


@router.delete("/groups/{chat_id}/addresses/{address_id}")
async def delete_group_address(
    chat_id: int, address_id: int, session: DbSession, max_user_id: MaxUserId
) -> dict[str, bool]:
    """Удалить адрес группы может только администратор MAX-чата."""
    chat = get_chat(session, chat_id)
    if chat is None or chat.chat_type != "chat":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Домовой чат не найден")
    bot = get_max_bot()
    if bot is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MAX-бот сейчас недоступен")
    try:
        member = await bot.get_chat_member(chat_id, max_user_id)
        is_admin = member is not None and bool(
            getattr(member, "is_admin", False) or getattr(member, "is_owner", False)
        )
        if not is_admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Удалить адрес может только администратор чата"
            )
        if not await bot_can_read_group(bot, chat_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "Боту нужно право «Читать все сообщения»")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Не удалось проверить права через MAX"
        ) from exc
    try:
        removed = remove_chat_address(session, chat_id, address_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if removed:
        session.commit()
        try:
            await announce_connected_group(bot, chat_id)
        except Exception:
            logger.exception("Не удалось обновить сообщение после удаления адреса чата")
    return {"removed": removed}

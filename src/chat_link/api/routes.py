from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from maxapi.utils.deep_linking import create_start_link

from chat_link.api.schemas import (
    AddressOption,
    AddressSearchResponse,
    AddressSelectRequest,
    AddressSelectResponse,
)
from chat_link.handlers import (
    announce_connected_group,
    bind_existing_chat_member,
    connect_added_group_to_address,
    create_request,
    get_address_catalog,
    mark_waiting_group,
)
from project.api_deps import DbSession, get_max_user_id
from project.max_runtime import get_max_bot
from user_chat.handlers import list_chats_by_address, set_member_address

router = APIRouter(prefix="/chat-link", tags=["chat-link"])
MaxUserId = Annotated[int, Depends(get_max_user_id)]


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


@router.get("/addresses/nearest", response_model=AddressSearchResponse)
def nearest_addresses(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> AddressSearchResponse:
    items = [_option(row) for row in get_address_catalog().nearest(lat, lon, limit=5)]
    return AddressSearchResponse(items=items)


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
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
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
        await announce_connected_group(
            bot,
            payload.chat_id,
            requester_added=outcome.requester_added,
            address_text=address.address_text,
            additional=outcome.message is not None,
        )
        return AddressSelectResponse(
            address=_option(address),
            mode="group_connected",
            chats=[],
        )

    chats = [
        chat
        for chat in list_chats_by_address(session, payload.address_id)
        if chat.chat_type == "chat"
    ]
    if chats:
        if bot is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MAX-бот сейчас недоступен")
        try:
            connected = False
            for chat in chats:
                if await bind_existing_chat_member(
                    bot, session, chat_id=chat.chat_id, max_user_id=max_user_id
                ):
                    set_member_address(
                        session,
                        chat.chat_id,
                        max_user_id=max_user_id,
                        address_id=payload.address_id,
                    )
                    connected = True
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except Exception as exc:
            # Ошибка MAX API не равна отсутствию в чате: запрещаем доступ до проверки.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Не удалось проверить членство через MAX"
            ) from exc
        if not connected:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Вы не состоите в домовом чате, привязанном к выбранному адресу.",
            )
        return AddressSelectResponse(
            address=_option(address),
            mode="already_member",
            chats=[],
        )

    try:
        request, _ = create_request(
            session,
            max_user_id=max_user_id,
            address_id=payload.address_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    mark_waiting_group(session, token=request.token)
    username = getattr(getattr(bot, "me", None), "username", None) if bot else None
    admin_link = create_start_link(username, f"chat_admin_{request.token}") if username else None
    return AddressSelectResponse(
        address=_option(address),
        mode="connect_group",
        token=request.token,
        admin_link=admin_link,
        chats=[],
    )

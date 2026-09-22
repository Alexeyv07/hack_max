from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from maxapi.utils.deep_linking import create_start_link

from chat_link.api.schemas import (
    AddressOption,
    AddressSearchResponse,
    AddressSelectRequest,
    AddressSelectResponse,
    ChatOption,
)
from chat_link.handlers import (
    announce_connected_group,
    connect_added_group_to_address,
    create_request,
    get_address_catalog,
    mark_waiting_group,
    request_admin_approval,
)
from events.api.deps import DbSession, get_max_user_id
from project.max_runtime import get_max_bot

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
        )
        return AddressSelectResponse(
            address=_option(address),
            mode="group_connected",
            chats=[],
        )

    try:
        request, chats = create_request(
            session,
            max_user_id=max_user_id,
            address_id=payload.address_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if not chats:
        mark_waiting_group(session, token=request.token)
    elif len(chats) == 1:
        try:
            request_admin_approval(
                session,
                token=request.token,
                chat_id=chats[0].chat_id,
            )
        except ValueError:
            # Legacy-чат без сохранённого администратора: оставляем прежний invite fallback.
            pass
        else:
            return AddressSelectResponse(
                address=_option(address),
                mode="approval_pending",
                token=request.token,
                chats=[],
            )
    username = getattr(getattr(bot, "me", None), "username", None) if bot else None
    admin_link = (
        create_start_link(username, f"chat_admin_{request.token}")
        if username and not chats
        else None
    )
    return AddressSelectResponse(
        address=_option(address),
        mode="existing_chat" if chats else "connect_group",
        token=request.token,
        admin_link=admin_link,
        chats=[
            ChatOption(
                chat_id=chat.chat_id,
                title=chat.title,
                invite_link=chat.invite_link,
            )
            for chat in chats
        ],
    )

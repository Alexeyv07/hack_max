"""HTTP-роуты онбординга адреса и домового чата."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from maxapi.enums.format import Format
from maxapi.utils.deep_linking import create_start_link

from auth.commands.home import send_home
from auth.commands.start import ADDRESS_PICKER_TEXT
from auth.handlers.residence import get_personal_address, set_personal_address
from chat_link.api.schemas import (
    AddressOption,
    AddressSearchResponse,
    AddressSelectRequest,
    AddressSelectResponse,
    ApiError,
    ChatLinkNavigationRequest,
    GroupAddressRemovedResponse,
    PersonalResidenceResponse,
    PostalAddressSearchResponse,
)
from chat_link.commands.keyboards import method_keyboard, setup_keyboard
from chat_link.commands.residence_screens import (
    residence_result_keyboard,
    residence_success_text,
    residence_wait_text,
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
from user_chat.handlers import (
    get_chat,
    linked_group_ids,
    list_chat_addresses,
    remove_chat_address,
    remove_user_from_chat,
    set_member_address,
)

router = APIRouter(prefix="/chat-link", tags=["ChatLink"])
MaxUserId = Annotated[int, Depends(get_max_user_id)]
logger = get_logger(__name__)

_AUTH_ERRORS = {
    status.HTTP_401_UNAUTHORIZED: {
        "description": "Нет заголовка `X-Max-User-Id`.",
        "model": ApiError,
    },
}


async def _send_selected_home(bot, session, max_user_id: int, *, notice: str | None = None) -> None:
    # Сначала сохраняем привязку. Ошибка отправки сообщения не должна откатывать адрес.
    session.commit()
    if bot is None:
        return
    try:
        await send_home(bot, session, max_user_id, notice=notice)
    except Exception:
        logger.exception("Не удалось отправить главную после выбора адреса через WebApp")


async def _send_residence_screen(
    bot, session, max_user_id: int, address, *, member: bool, resident_chat_id: int | None = None
) -> None:
    """Дать возможность продолжить WebApp-сценарий в личке, даже если WebView закрыт."""
    session.commit()
    try:
        await bot.send_message(
            user_id=max_user_id,
            text=(
                residence_success_text(address.address_text)
                if member
                else residence_wait_text(address.address_text)
            ),
            attachments=[
                residence_result_keyboard(
                    address.id, member=member, resident_chat_id=resident_chat_id
                )
            ],
            format=Format.HTML,
        )
    except Exception:
        logger.exception("Не удалось отправить экран выбора адреса в MAX")


def _option(row, score: float | None = None) -> AddressOption:
    return AddressOption(
        id=row.id,
        address_text=row.address_text,
        latitude=row.latitude,
        longitude=row.longitude,
        score=score,
    )


@router.get(
    "/addresses/search",
    response_model=AddressSearchResponse,
    summary="Поиск адреса по тексту",
    response_description="До 12 лучших совпадений с score",
    responses={
        status.HTTP_200_OK: {"model": AddressSearchResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "`q` короче 3 символов или длиннее 300.",
            "model": ApiError,
        },
    },
)
def search_addresses(
    q: Annotated[
        str,
        Query(
            min_length=3,
            max_length=300,
            description=(
                "Свободный текстовый запрос: улица, дом, район. "
                "Минимум 3 символа. Fuzzy + stem по каталогу Москвы."
            ),
            examples=["Варшавское 28", "Нагатинская наб"],
        ),
    ],
) -> AddressSearchResponse:
    """
    Текстовый поиск дома в адресном каталоге (один из 4 способов ввода адреса).

    **Без** `X-Max-User-Id` — публичный lookup для пикера webapp.
    """
    items = [_option(row, score) for row, score in get_address_catalog().search(q, limit=12)]
    return AddressSearchResponse(items=items)


@router.get(
    "/addresses/postal",
    response_model=PostalAddressSearchResponse,
    summary="Адреса по почтовому индексу",
    response_description="Страница домов индекса + total",
    responses={
        status.HTTP_200_OK: {"model": PostalAddressSearchResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "`code` не ровно 6 цифр.",
            "model": ApiError,
        },
    },
)
def search_postal_addresses(
    code: Annotated[
        str,
        Query(
            pattern=r"^\d{6}$",
            description="Почтовый индекс РФ, ровно 6 цифр (например `117405`).",
            examples=["117405"],
        ),
    ],
    q: Annotated[
        str,
        Query(
            max_length=120,
            description="Опциональный текстовый фильтр внутри индекса (улица / дом).",
            examples=["Варшавское"],
        ),
    ] = "",
    offset: Annotated[
        int,
        Query(ge=0, description="Смещение для пагинации списка домов.", examples=[0]),
    ] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=30, description="Размер страницы (1–30).", examples=[12]),
    ] = 12,
) -> PostalAddressSearchResponse:
    """
    Список домов по почтовому индексу (второй способ ввода адреса).

    `total` — полное число совпадений; листай через `offset` / `limit`.
    """
    rows, total = get_address_catalog().postal_addresses(code, query=q, offset=offset, limit=limit)
    return PostalAddressSearchResponse(items=[_option(row) for row in rows], total=total)


@router.get(
    "/addresses/nearest",
    response_model=AddressSearchResponse,
    summary="Ближайшие адреса к точке на карте",
    response_description="До 5 ближайших домов",
    responses={
        status.HTTP_200_OK: {"model": AddressSearchResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "lat/lon вне допустимого диапазона.",
            "model": ApiError,
        },
    },
)
def nearest_addresses(
    lat: Annotated[
        float,
        Query(ge=-90, le=90, description="Широта точки с карты (Yandex).", examples=[55.65012]),
    ],
    lon: Annotated[
        float,
        Query(
            ge=-180,
            le=180,
            description="Долгота точки с карты (Yandex).",
            examples=[37.61890],
        ),
    ],
) -> AddressSearchResponse:
    """
    Nearest-lookup для пикера на карте (третий способ ввода адреса).

    Клиент ставит метку → шлёт lat/lon → показывает ближайшие дома каталога.
    """
    items = [_option(row) for row in get_address_catalog().nearest(lat, lon, limit=5)]
    return AddressSearchResponse(items=items)


@router.get(
    "/residence",
    response_model=PersonalResidenceResponse,
    summary="Текущий выбранный дом пользователя",
    response_description="Адрес или null",
    responses={
        status.HTTP_200_OK: {"model": PersonalResidenceResponse},
        **_AUTH_ERRORS,
    },
)
def get_residence(session: DbSession, max_user_id: MaxUserId) -> PersonalResidenceResponse:
    """
    Вернуть личный адрес жителя, если он выбран **и** по нему есть linked MAX-чат.

    Иначе `address=null` (nearby-лента будет пустой, пока пользователь не пройдёт онбординг).
    """
    address = get_personal_address(session, max_user_id)
    if address is not None and not linked_group_ids(session, max_user_id, address_id=address.id):
        address = None
    return PersonalResidenceResponse(address=_option(address) if address is not None else None)


@router.post(
    "/select",
    response_model=AddressSelectResponse,
    summary="Выбрать адрес / привязать домовой чат",
    response_description="Исход онбординга (`mode`) + опциональный admin deep-link",
    responses={
        status.HTTP_200_OK: {
            "model": AddressSelectResponse,
            "description": (
                "`resident_address` — членство в выбранном чате подтверждено; "
                "`not_member` — членство не подтверждено, при `onboarding=true` "
                "пользователь может повторить проверку."
            ),
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Пользователь не состоит в указанном чате.",
            "model": ApiError,
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "`address_id` нет в каталоге.",
            "model": ApiError,
        },
        status.HTTP_409_CONFLICT: {
            "description": "Конфликт привязки / бизнес-правило (см. `detail`).",
            "model": ApiError,
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Переданы и `chat_id`, и `resident_chat_id`.",
            "model": ApiError,
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "MAX-бот недоступен или не удалось проверить членство.",
            "model": ApiError,
        },
        **_AUTH_ERRORS,
    },
)
async def select_address(
    payload: AddressSelectRequest,
    session: DbSession,
    max_user_id: MaxUserId,
) -> AddressSelectResponse:
    """
    Центральная ручка онбординга webapp после выбора дома.

    ### Режимы тела запроса
    | Поля | Поведение |
    |------|-----------|
    | только `address_id` | `resolve_residence`: сохранить дом / проверить чат / предложить админу |
    | `address_id` + `chat_id` | админ привязывает только что добавленную группу к адресу |
    | `address_id` + `resident_chat_id` | житель подтверждает членство в уже существующем чате |

    `chat_id` и `resident_chat_id` **взаимоисключающие**.

    ### Пример: житель уже состоит в домовом чате
    `{"address_id": 881, "resident_chat_id": 123456789, "onboarding": true}`
    → HTTP 200, `mode=resident_address`. В личку приходит сообщение об успехе
    с кнопкой «На главную».

    ### Пример: житель ещё не вступил
    Тот же запрос → HTTP 200, `mode=not_member`. В личку приходит предложение
    вступить через «Госуслуги Дом» с кнопками «Проверить еще раз» и «Назад».
    Повторная проверка выполняется заново через MAX. Без `onboarding=true`
    в сценарии с `resident_chat_id` сохраняется прежний HTTP 403.

    Требует живой процесс бота (`runtime.enable_bot`) для проверок членства.
    """
    address = get_address_catalog().get(payload.address_id)
    if address is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Адрес не найден")
    bot = get_max_bot()
    if payload.chat_id is not None and payload.resident_chat_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Укажите только один тип привязки"
        )
    if payload.resident_chat_id is not None:
        if bot is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MAX-бот сейчас недоступен")
        try:
            if not await bind_existing_chat_member(
                bot, session, chat_id=payload.resident_chat_id, max_user_id=max_user_id
            ):
                if payload.onboarding:
                    if not any(
                        item.id == payload.address_id
                        for item in list_chat_addresses(session, payload.resident_chat_id)
                    ):
                        raise HTTPException(
                            status.HTTP_409_CONFLICT, "Выбранный адрес не привязан к этому чату"
                        )
                    remove_user_from_chat(
                        session, payload.resident_chat_id, max_user_id=max_user_id
                    )
                    await _send_residence_screen(
                        bot,
                        session,
                        max_user_id,
                        address,
                        member=False,
                        resident_chat_id=payload.resident_chat_id,
                    )
                    return AddressSelectResponse(address=_option(address), mode="not_member")
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
        await _send_residence_screen(bot, session, max_user_id, address, member=True)
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
        await _send_residence_screen(bot, session, max_user_id, address, member=True)
        return AddressSelectResponse(address=_option(address), mode="personal_address", chats=[])

    admin_link = None
    if outcome.mode == "no_chat" and outcome.token:
        username = getattr(getattr(bot, "me", None), "username", None)
        if username:
            admin_link = create_start_link(username, f"chat_admin_{outcome.token}")
    session.commit()
    if outcome.mode == "not_member":
        notice = residence_wait_text(address.address_text)
        attachments = [residence_result_keyboard(address.id, member=False)]
    else:
        notice = (
            f"По адресу {address.address_text} пока нет подключённого домового чата. "
            "Скопируйте приглашение для администратора или нажмите «Я администратор»."
        )
        attachments = [setup_keyboard(admin_link, address.address_text)]
    try:
        await bot.send_message(
            user_id=max_user_id,
            text=notice,
            attachments=attachments,
            format=Format.HTML,
        )
    except Exception:
        logger.exception("Не удалось отправить результат выбора адреса в MAX")
    return AddressSelectResponse(
        address=_option(address),
        mode=outcome.mode,
        token=outcome.token,
        admin_link=admin_link,
        chats=[],
    )


@router.post(
    "/navigation",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Синхронизировать переход в миниапке с личным чатом бота",
    response_description="Экран отправлен в личку; тело ответа отсутствует (204)",
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": "Экран отправлен пользователю в личные сообщения."
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "MAX-бот недоступен или не удалось отправить экран.",
            "model": ApiError,
        },
        **_AUTH_ERRORS,
    },
)
async def navigate_chat_link(
    payload: ChatLinkNavigationRequest, session: DbSession, max_user_id: MaxUserId
) -> Response:
    """
    Повторить переход из миниапки в личном чате бота.

    - `{"action": "home"}` — показать главное меню после кнопки «На главную».
    - `{"action": "choose_address"}` — показать выбор способа ввода адреса после «Назад».

    При успехе возвращает HTTP 204 **без JSON-тела**. Наличие заголовка
    `X-Max-User-Id` обязательно; при ошибке отправки экрана возвращается 503.
    """
    bot = get_max_bot()
    if bot is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MAX-бот сейчас недоступен")
    try:
        if payload.action == "home":
            await send_home(bot, session, max_user_id)
        else:
            await bot.send_message(
                user_id=max_user_id,
                text=ADDRESS_PICKER_TEXT,
                attachments=[method_keyboard(bot)],
                format=Format.HTML,
            )
    except Exception as exc:
        logger.exception("Не удалось синхронизировать экран миниапки с личкой")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Не удалось показать экран в боте"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/groups/{chat_id}/addresses/{address_id}",
    response_model=GroupAddressRemovedResponse,
    summary="Снять адрес с домового чата (только админ)",
    response_description="Флаг, был ли адрес удалён",
    responses={
        status.HTTP_200_OK: {"model": GroupAddressRemovedResponse},
        status.HTTP_403_FORBIDDEN: {
            "description": "Вызывающий не админ/владелец чата.",
            "model": ApiError,
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Чат не найден или это не group chat.",
            "model": ApiError,
        },
        status.HTTP_409_CONFLICT: {
            "description": "Боту нужно право «Читать все сообщения» / иное бизнес-ограничение.",
            "model": ApiError,
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "MAX-бот недоступен.",
            "model": ApiError,
        },
        **_AUTH_ERRORS,
    },
)
async def delete_group_address(
    chat_id: Annotated[int, Path(description="ID MAX group chat.", examples=[123456789], ge=1)],
    address_id: Annotated[int, Path(description="ID адреса для отвязки.", examples=[881], ge=1)],
    session: DbSession,
    max_user_id: MaxUserId,
) -> GroupAddressRemovedResponse:
    """
    Удалить привязку адреса у домовой группы.

    Разрешено **только** администратору / владельцу MAX-чата.
    Бот должен иметь право читать все сообщения группы.
    """
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
    return GroupAddressRemovedResponse(removed=removed)

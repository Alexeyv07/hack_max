"""Схемы HTTP API chat-link (онбординг адреса и домового чата)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AddressOption(BaseModel):
    """Один адрес из каталога (StreetCatalog / addresses)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": 881,
                    "address_text": "Москва, Варшавское шоссе, 28к1",
                    "latitude": 55.65012,
                    "longitude": 37.61890,
                    "score": 0.94,
                }
            ]
        }
    )

    id: int = Field(
        description="ID строки в таблице `addresses`.",
        examples=[881],
        ge=1,
    )
    address_text: str = Field(
        description="Полная человекочитаемая подпись адреса.",
        examples=["Москва, Варшавское шоссе, 28к1"],
        min_length=1,
    )
    latitude: float = Field(
        description="Широта дома / точки.",
        examples=[55.65012],
    )
    longitude: float = Field(
        description="Долгота дома / точки.",
        examples=[37.61890],
    )
    score: float | None = Field(
        default=None,
        description=(
            "Оценка релевантности textual/fuzzy поиска (`/addresses/search`). "
            "Для postal/nearest обычно `null`."
        ),
        examples=[0.94],
    )


class AddressSearchResponse(BaseModel):
    """Список адресов (text search / nearest)."""

    items: list[AddressOption] = Field(
        description="Варианты адреса, от лучших к худшим.",
    )


class PostalAddressSearchResponse(AddressSearchResponse):
    """Страница адресов по почтовому индексу."""

    total: int = Field(
        description="Полное число совпадений по индексу (до пагинации offset/limit).",
        examples=[48],
        ge=0,
    )


class PersonalResidenceResponse(BaseModel):
    """Текущий личный адрес пользователя (если выбран и чат привязан)."""

    address: AddressOption | None = Field(
        default=None,
        description=(
            "Выбранный дом. `null` — адрес не выбран, либо по адресу ещё нет "
            "linked group для этого пользователя."
        ),
    )


class AddressSelectRequest(BaseModel):
    """Тело выбора адреса / привязки чата."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"address_id": 881},
                {"address_id": 881, "chat_id": 123456789},
                {"address_id": 881, "resident_chat_id": 123456789},
            ]
        }
    )

    address_id: int = Field(
        description="ID адреса из каталога (результат search / postal / nearest).",
        examples=[881],
        ge=1,
    )
    chat_id: int | None = Field(
        default=None,
        description=(
            "ID MAX group chat, который админ только что добавил к боту: "
            "привязать группу к `address_id` (mode `group_connected`). "
            "**Нельзя** передавать вместе с `resident_chat_id`."
        ),
        examples=[123456789],
    )
    resident_chat_id: int | None = Field(
        default=None,
        description=(
            "ID уже существующего домового чата: проверить членство пользователя "
            "и сохранить адрес жителя (mode `resident_address`). "
            "**Нельзя** передавать вместе с `chat_id`."
        ),
        examples=[123456789],
    )


class ChatOption(BaseModel):
    """Краткая карточка домового чата (legacy-поле ответа)."""

    chat_id: int = Field(description="ID чата в Max.", examples=[123456789])
    title: str = Field(description="Название чата.", examples=["Чат соседей · Варшавское 28"])
    invite_link: str | None = Field(
        default=None,
        description="Invite-ссылка, если известна.",
        examples=["https://max.ru/..."],
    )


class AddressSelectResponse(BaseModel):
    """Результат выбора адреса / онбординга чата."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "address": {
                        "id": 881,
                        "address_text": "Москва, Варшавское шоссе, 28к1",
                        "latitude": 55.65012,
                        "longitude": 37.61890,
                        "score": None,
                    },
                    "mode": "personal_address",
                    "token": None,
                    "admin_link": None,
                    "chats": [],
                },
                {
                    "address": {
                        "id": 881,
                        "address_text": "Москва, Варшавское шоссе, 28к1",
                        "latitude": 55.65012,
                        "longitude": 37.61890,
                        "score": None,
                    },
                    "mode": "no_chat",
                    "token": "abc123",
                    "admin_link": "https://max.ru/...",
                    "chats": [],
                },
            ]
        }
    )

    address: AddressOption = Field(description="Выбранный адрес (всегда возвращается).")
    mode: str = Field(
        description=(
            "Исход онбординга:\n"
            "- `personal_address` — дом сохранён, доступ к nearby открыт;\n"
            "- `resident_address` — подтверждено членство в существующем чате;\n"
            "- `group_connected` — админ привязал новую группу к адресу;\n"
            "- `not_member` — чат по адресу есть, но пользователь не состоит в нём "
            "(нужен вход через «Госуслуги Дом»);\n"
            "- `no_chat` — чата ещё нет: нужен админ / deep-link (`admin_link` / `token`)."
        ),
        examples=["personal_address", "no_chat", "not_member", "group_connected"],
    )
    token: str | None = Field(
        default=None,
        description="Токен deep-link для админа (`chat_admin_{token}`), если `mode=no_chat`.",
        examples=["abc123"],
    )
    admin_link: str | None = Field(
        default=None,
        description="Готовая start-ссылка бота для администратора чата (если username бота известен).",
        examples=["https://max.ru/..."],
    )
    chats: list[ChatOption] = Field(
        default_factory=list,
        description="Список чатов (сейчас обычно пустой — зарезервировано контрактом).",
    )


class GroupAddressRemovedResponse(BaseModel):
    """Результат удаления адреса у домового чата."""

    removed: bool = Field(
        description="`true`, если адрес был привязан и успешно снят; `false` — нечего удалять.",
        examples=[True],
    )


class ApiError(BaseModel):
    """Ошибка FastAPI."""

    detail: str = Field(
        description="Текст ошибки.",
        examples=["Адрес не найден"],
    )

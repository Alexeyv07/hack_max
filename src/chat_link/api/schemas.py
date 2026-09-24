from __future__ import annotations

from pydantic import BaseModel, Field


class AddressOption(BaseModel):
    id: int
    address_text: str
    latitude: float
    longitude: float
    score: float | None = None


class AddressSearchResponse(BaseModel):
    items: list[AddressOption]


class PostalAddressSearchResponse(AddressSearchResponse):
    total: int


class AddressSelectRequest(BaseModel):
    address_id: int
    chat_id: int | None = None
    resident_chat_id: int | None = None


class ChatOption(BaseModel):
    chat_id: int
    title: str
    invite_link: str | None = None


class AddressSelectResponse(BaseModel):
    address: AddressOption
    mode: str
    token: str | None = None
    admin_link: str | None = None
    chats: list[ChatOption] = Field(default_factory=list)

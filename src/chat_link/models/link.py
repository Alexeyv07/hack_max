"""Доменные модели onboarding-flow подключения чата."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ChatLinkStatus(StrEnum):
    """Явные состояния заявки, даже пока approve администратора замокан."""

    PENDING_BOT = "pending_bot"
    PENDING_ADMIN = "pending_admin"
    READY = "ready"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ChatLink:
    token: str
    address_id: int
    created_by_user_id: int
    status: ChatLinkStatus
    chat_id: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AddressConnectResult:
    """Результат шага «пользователь ввёл адрес»."""

    address_id: int
    address_text: str
    chat_ids: tuple[int, ...]
    joined_chat_id: int | None = None

    @property
    def needs_new_chat(self) -> bool:
        return not self.chat_ids

    @property
    def needs_chat_choice(self) -> bool:
        return len(self.chat_ids) > 1

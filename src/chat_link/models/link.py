from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChatLinkStatus(StrEnum):
    WAITING_GROUP = "waiting_group"
    WAITING_JOIN = "waiting_join"
    WAITING_APPROVAL = "waiting_approval"
    APPROVAL_SENT = "approval_sent"
    CONNECTED = "connected"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ChatLink:
    id: int
    token: str
    requester_user_id: int
    address_id: int
    status: ChatLinkStatus
    chat_id: int | None = None
    admin_user_id: int | None = None

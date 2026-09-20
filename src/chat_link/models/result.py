from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JoinOutcome:
    joined: bool
    message: str
    invite_link: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectOutcome:
    connected: bool
    chat_id: int
    requester_added: bool
    message: str | None = None

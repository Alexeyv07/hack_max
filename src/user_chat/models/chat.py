"""Доменные представления чата и его участников (не ORM)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChatCreate:
    chat_id: int
    address_id: int
    title: str = "Чат соседей"
    # Закрытый чат может ещё не иметь приглашения.
    invite_link: str | None = None


@dataclass(frozen=True, slots=True)
class Chat:
    chat_id: int
    address_id: int
    title: str
    invite_link: str | None


@dataclass(frozen=True, slots=True)
class ChatMember:
    user_id: int  # users.id; не путать с MAX id
    max_user_id: int
    name: str | None
    username: str | None

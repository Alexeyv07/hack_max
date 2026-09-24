"""Доменные представления пользователей Max (не ORM)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class MaxUserPayload:
    """Нормализованные данные пользователя из событий Bot API Max."""

    max_user_id: int
    name: str | None = None
    username: str | None = None
    chat_id: int | None = None
    payload: str | None = None

    @classmethod
    def from_event_user(
        cls,
        user: Any,
        *,
        chat_id: int | None = None,
        payload: str | None = None,
    ) -> MaxUserPayload:
        """
        Собрать payload из объекта пользователя maxapi или из словаря.

        Поддерживаются и attribute-style (maxapi), и dict-style входы.
        """
        if isinstance(user, dict):
            max_user_id = int(user["user_id"])
            name = user.get("name") or user.get("first_name")
            username = user.get("username")
        else:
            max_user_id = int(user.user_id)
            name = getattr(user, "name", None) or getattr(user, "first_name", None)
            username = getattr(user, "username", None)

        return cls(
            max_user_id=max_user_id,
            name=name,
            username=username,
            chat_id=chat_id,
            payload=payload,
        )


@dataclass(slots=True)
class User:
    """Пользователь на уровне приложения."""

    id: int | None
    max_user_id: int
    name: str | None
    username: str | None
    chat_id: int | None
    start_payload: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_seen_at: datetime | None = None
    is_new: bool = False  # Только первый insert пользователя, без дополнительной миграции.

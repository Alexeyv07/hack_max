"""FastAPI-зависимости: БД и текущий пользователь webapp."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from chat_link.handlers.membership import list_memberships_for_user
from chat_link.models.membership import ChatMembership
from project.database import get_session_factory


def get_db_session() -> Generator[Session, None, None]:
    """Сессия на запрос: commit при успехе, rollback при ошибке."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db_session)]


def get_max_user_id(
    x_max_user_id: Annotated[
        int | None,
        Header(
            alias="X-Max-User-Id",
            description="ID пользователя Max (webapp и бот знают одного и того же user)",
        ),
    ] = None,
) -> int:
    """
    Идентификация пользователя для webapp.

    Пока без проверки initData Max: фронт передаёт max_user_id в заголовке.
    Бот уже пишет того же пользователя в `users` на /start.
    """
    if x_max_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нужен заголовок X-Max-User-Id",
        )
    return x_max_user_id


def get_user_memberships(
    session: DbSession,
    max_user_id: Annotated[int, Depends(get_max_user_id)],
) -> list[ChatMembership]:
    """Чаты пользователя → гео для feed/map. Пока mock (KAN-5)."""
    memberships = list_memberships_for_user(session, max_user_id)
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден или не состоит в чатах. Сначала /start в боте.",
        )
    return memberships

"""FastAPI-зависимости: БД и текущий пользователь webapp."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

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

    Фронт берёт id из Max Bridge (initDataUnsafe.user.id) и шлёт в заголовке.
    """
    if x_max_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нужен заголовок X-Max-User-Id",
        )
    return x_max_user_id

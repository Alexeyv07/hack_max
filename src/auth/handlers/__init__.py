"""Обработчики авторизации (здесь же SQLAlchemy-запросы)."""

from auth.handlers.authorize import (
    authorize_from_event,
    authorize_user,
    get_user_by_max_id,
)

__all__ = ["authorize_from_event", "authorize_user", "get_user_by_max_id"]

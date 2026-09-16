"""Членство пользователя в чатах соседей."""

from __future__ import annotations

from sqlalchemy.orm import Session

from auth.handlers.authorize import get_user_by_max_id
from chat_link.models.membership import ChatMembership
from project.config import get_settings
from project.logging_setup import get_logger

logger = get_logger(__name__)


def list_memberships_for_user(session: Session, max_user_id: int) -> list[ChatMembership]:
    """
    Чаты пользователя с гео для ленты/карты.

    MOCK (KAN-5 ещё нет): если пользователь есть в `users` после /start бота —
    отдаём один демо-чат в центре мока (Москва). Иначе — пустой список.
    """
    user = get_user_by_max_id(session, max_user_id)
    if user is None:
        logger.info("Нет пользователя max_user_id=%s — чаты не резолвим", max_user_id)
        return []

    settings = get_settings()
    # TODO(KAN-5): SELECT из users_chat + address по user.id
    mock = ChatMembership(
        chat_id=900_001,
        title="Mock: чат соседей (демо)",
        lat=55.75,
        lon=37.62,
        nearby_radius_m=settings.events.nearby_radius_m,
        city_radius_m=settings.events.city_radius_m,
    )
    logger.debug(
        "MOCK memberships max_user_id=%s → chat_id=%s",
        max_user_id,
        mock.chat_id,
    )
    return [mock]

"""Приветственная обложка привязана к первой авторизации, не к команде /start."""

from __future__ import annotations

from auth.handlers.authorize import authorize_user
from auth.models.user import MaxUserPayload


def test_only_new_user_has_is_new_flag(db_session) -> None:
    payload = MaxUserPayload(max_user_id=42, name="Алексей", chat_id=123)
    first = authorize_user(db_session, payload)
    second = authorize_user(db_session, payload)
    assert first.is_new is True
    assert second.is_new is False
    assert first.id == second.id

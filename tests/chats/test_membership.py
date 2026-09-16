"""Тесты mock memberships."""

from __future__ import annotations

from auth.handlers.authorize import authorize_user
from auth.models.user import MaxUserPayload
from chat_link.handlers.membership import list_memberships_for_user


def test_memberships_empty_without_user(db_session) -> None:
    assert list_memberships_for_user(db_session, max_user_id=1) == []


def test_memberships_mock_when_user_exists(db_session) -> None:
    authorize_user(
        db_session,
        MaxUserPayload(max_user_id=7, name="A", username="a"),
    )
    memberships = list_memberships_for_user(db_session, max_user_id=7)
    assert len(memberships) == 1
    assert memberships[0].lat == 55.75
    assert memberships[0].chat_id == 900_001

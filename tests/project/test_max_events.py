from __future__ import annotations

from types import SimpleNamespace

from project.max_events import is_private_chat_event


def test_private_chat_detector_uses_max_recipient_type() -> None:
    for chat_type, expected in [("dialog", True), ("chat", False), ("channel", False)]:
        event = SimpleNamespace(
            chat_id=123,
            message=SimpleNamespace(recipient=SimpleNamespace(chat_type=chat_type, chat_id=123)),
        )
        assert is_private_chat_event(event) is expected


def test_private_chat_detector_handles_bot_started_without_message() -> None:
    assert is_private_chat_event(SimpleNamespace(chat_id=-123)) is False
    assert is_private_chat_event(SimpleNamespace(chat_id=123)) is True
    assert (
        is_private_chat_event(SimpleNamespace(chat_id=123, chat=SimpleNamespace(type="chat")))
        is False
    )

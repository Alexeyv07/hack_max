"""Реальный источник #итого: сообщения MAX → БД → дайджест."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from address.db.address import AddressRow
from notify.chat_source import load_chat_messages, persist_digest_message
from notify.db import NotifyChatMessageRow, NotifyDigestRow
from notify.worker import run_digest_cycle
from parse_chat.handlers.process import process_chat_event
from parse_chat.models.message import RawChatMessage
from project.config import NotifyConfig
from user_chat.db.chat import ChatRow


def _chat(session, chat_id: int) -> None:
    address = AddressRow(
        address_text=f"Москва, Тестовый дом {abs(chat_id)}",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6200000"),
    )
    session.add(address)
    session.flush()
    session.add(ChatRow(chat_id=chat_id, title="Домовой чат", address=address, chat_type="chat"))
    session.flush()


def _raw(chat_id: int, mid: str, *, text: str, when: datetime) -> RawChatMessage:
    return RawChatMessage(
        chat_id=chat_id,
        message_id=mid,
        text=text,
        sender_user_id=123,
        sender_is_bot=False,
        published_at=when,
    )


def test_persist_only_human_text_and_no_duplicate(db_session) -> None:
    chat_id = -8001
    _chat(db_session, chat_id)
    when = datetime(2026, 9, 23, 12, tzinfo=UTC)
    msg = _raw(chat_id, "1", text="Привет! Что у нас с отоплением?", when=when)
    assert persist_digest_message(db_session, msg)
    assert not persist_digest_message(db_session, msg)
    assert not persist_digest_message(db_session, _raw(chat_id, "2", text="/address", when=when))
    assert not persist_digest_message(db_session, _raw(chat_id, "3", text="  ", when=when))
    bot_msg = _raw(chat_id, "4", text="#итого", when=when)
    assert not persist_digest_message(
        db_session,
        RawChatMessage(
            chat_id=bot_msg.chat_id,
            message_id=bot_msg.message_id,
            text=bot_msg.text,
            sender_user_id=456,
            sender_is_bot=True,
            published_at=when,
        ),
    )
    assert db_session.query(NotifyChatMessageRow).count() == 1


def test_loader_is_chat_scoped_and_id_cursor_handles_equal_timestamps(
    session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _chat(session, -8002)
        _chat(session, -8003)
        when = datetime(2026, 9, 23, 12, tzinfo=UTC)
        for chat_id, mid in [(-8002, "a"), (-8003, "b"), (-8002, "c")]:
            assert persist_digest_message(
                session, _raw(chat_id, mid, text=f"Сообщение {mid}", when=when)
            )
        session.commit()

    monkeypatch.setattr("notify.chat_source.get_session_factory", lambda: session_factory)
    rows = asyncio.run(load_chat_messages(-8002, None))
    assert [row.text for row in rows] == ["Сообщение a", "Сообщение c"]
    assert all(row.created_at == when.replace(tzinfo=None) for row in rows)
    newer = asyncio.run(load_chat_messages(-8002, None, after_id=rows[0].row_id))
    assert [row.text for row in newer] == ["Сообщение c"]
    assert asyncio.run(load_chat_messages(-8003, None, after_id=rows[-1].row_id)) == []


def test_real_loader_sends_only_after_31_and_uses_id_cursor(session_factory, monkeypatch) -> None:
    chat_id = -8004
    when = datetime(2026, 9, 23, 12, tzinfo=UTC)
    with session_factory() as session:
        _chat(session, chat_id)
        for index in range(30):
            assert persist_digest_message(
                session, _raw(chat_id, f"msg-{index}", text=f"Текст {index}", when=when)
            )
        session.commit()

    monkeypatch.setattr("notify.chat_source.get_session_factory", lambda: session_factory)
    config = NotifyConfig(
        timezone="Europe/Moscow",
        digest_hour=20,
        digest_jitter_minutes=0,
        digest_min_new_messages=30,
    )
    bot = SimpleNamespace(send_message=AsyncMock(), me=SimpleNamespace(username="test_bot"))

    async def summarize(messages, _config):
        assert len(messages) == 31
        return "• Новости дома"

    first = datetime(2026, 9, 23, 18, tzinfo=UTC)
    assert (
        asyncio.run(
            run_digest_cycle(
                bot,
                now=first,
                config=config,
                session_factory=session_factory,
                summarizer=summarize,
            )
        )
        == 0
    )
    with session_factory() as session:
        state = session.get(NotifyDigestRow, chat_id)
        assert state.last_message_id is None
        assert persist_digest_message(session, _raw(chat_id, "msg-30", text="Текст 30", when=when))
        session.commit()

    assert (
        asyncio.run(
            run_digest_cycle(
                bot,
                now=first + timedelta(days=1),
                config=config,
                session_factory=session_factory,
                summarizer=summarize,
            )
        )
        == 1
    )
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["text"].startswith("#итого")
    with session_factory() as session:
        state = session.get(NotifyDigestRow, chat_id)
        assert state.last_message_id is not None
        assert state.last_message_at is not None
        # Уже обработанные тексты удаляются после успешной отправки.
        assert session.query(NotifyChatMessageRow).count() == 0


def test_capture_still_runs_when_heavy_parser_disabled(db_session, monkeypatch) -> None:
    _chat(db_session, -8005)

    @contextmanager
    def fake_scope():
        yield db_session
        db_session.flush()

    monkeypatch.setattr("parse_chat.handlers.process.session_scope", fake_scope)
    monkeypatch.setattr(
        "parse_chat.handlers.process.get_settings",
        lambda: SimpleNamespace(
            runtime=SimpleNamespace(enable_chat_parser=False),
            chat_parser=SimpleNamespace(enabled=False),
            notify=SimpleNamespace(enabled=True),
        ),
    )
    event = SimpleNamespace(
        message=SimpleNamespace(
            recipient=SimpleNamespace(chat_id=-8005, chat_type="chat"),
            body=SimpleNamespace(mid="test-1", text="В подъезде отключили воду", attachments=None),
            sender=SimpleNamespace(user_id=123, is_bot=False),
            timestamp=1_700_000_000_000,
        )
    )
    assert process_chat_event(event) is False
    assert db_session.query(NotifyChatMessageRow).one().text == "В подъезде отключили воду"


def test_failed_send_keeps_messages_and_cursor(session_factory, monkeypatch) -> None:
    chat_id = -8006
    when = datetime(2026, 9, 23, 12, tzinfo=UTC)
    with session_factory() as session:
        _chat(session, chat_id)
        for index in range(31):
            persist_digest_message(
                session, _raw(chat_id, f"msg-{index}", text=f"Текст {index}", when=when)
            )
        session.commit()

    monkeypatch.setattr("notify.chat_source.get_session_factory", lambda: session_factory)
    config = NotifyConfig(timezone="Europe/Moscow", digest_hour=20, digest_jitter_minutes=0)
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("MAX offline")))

    async def summarize(_messages, _config):
        return "• Новости дома"

    assert (
        asyncio.run(
            run_digest_cycle(
                bot,
                now=datetime(2026, 9, 23, 18, tzinfo=UTC),
                config=config,
                session_factory=session_factory,
                summarizer=summarize,
            )
        )
        == 0
    )
    with session_factory() as session:
        assert session.get(NotifyDigestRow, chat_id) is None
        assert session.query(NotifyChatMessageRow).count() == 31

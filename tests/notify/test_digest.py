from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from address.db.address import AddressRow
from notify.chat_source import ChatMessage
from notify.db import NotifyDigestRow
from notify.digest import build_template_digest, digest_scheduled_at
from notify.worker import run_digest_cycle, run_notify_worker
from project.config import NotifyConfig
from user_chat.db import ChatRow


def _messages(count: int, *, start: datetime) -> list[ChatMessage]:
    return [
        ChatMessage(text=f"Сообщение {index}", created_at=start + timedelta(minutes=index))
        for index in range(count)
    ]


def _add_chat(session_factory, chat_id: int) -> None:
    with session_factory() as session:
        address = AddressRow(
            address_text=f"Москва, Тестовая улица, д. {abs(chat_id)}",
            latitude=Decimal("55.7500000"),
            longitude=Decimal("37.6200000"),
        )
        session.add(address)
        session.flush()
        session.add(
            ChatRow(
                chat_id=chat_id,
                title="Домовой чат",
                address=address,
                chat_type="chat",
            )
        )
        session.commit()


def test_digest_schedule_is_stable_and_differs_by_chat() -> None:
    cfg = NotifyConfig(
        timezone="Europe/Moscow",
        digest_hour=20,
        digest_jitter_minutes=60,
    )
    day = date(2026, 9, 21)

    first = digest_scheduled_at(-5001, day, cfg)
    repeated = digest_scheduled_at(-5001, day, cfg)
    other = digest_scheduled_at(-5002, day, cfg)

    assert first == repeated
    assert first != other
    base = datetime(2026, 9, 21, 20, tzinfo=first.tzinfo)
    assert abs((first - base).total_seconds()) <= 60 * 60


def test_30_messages_are_not_summarized(session_factory) -> None:
    cfg = NotifyConfig(
        timezone="Europe/Moscow",
        digest_hour=20,
        digest_jitter_minutes=0,
        digest_min_new_messages=30,
    )
    now = datetime(2026, 9, 21, 18, 30, tzinfo=UTC)
    _add_chat(session_factory, -7001)
    messages = _messages(30, start=now - timedelta(hours=2))

    async def loader(chat_id, after):
        assert chat_id == -7001
        assert after is None
        return messages

    async def summarizer(_messages, _config):
        raise AssertionError("На 30 сообщениях summarizer вызываться не должен")

    bot = SimpleNamespace(send_message=AsyncMock(), me=SimpleNamespace(username="test_bot"))
    sent = asyncio.run(
        run_digest_cycle(
            bot,
            now=now,
            config=cfg,
            session_factory=session_factory,
            message_loader=loader,
            summarizer=summarizer,
        )
    )

    assert sent == 0
    bot.send_message.assert_not_awaited()
    with session_factory() as session:
        state = session.get(NotifyDigestRow, -7001)
        assert state is not None
        assert state.last_digest_date == date(2026, 9, 21)
        assert state.last_message_at is None


def test_31_messages_are_summarized_and_cursor_moves(session_factory) -> None:
    cfg = NotifyConfig(
        timezone="Europe/Moscow",
        digest_hour=20,
        digest_jitter_minutes=0,
        digest_min_new_messages=30,
    )
    now = datetime(2026, 9, 21, 18, 30, tzinfo=UTC)
    _add_chat(session_factory, -7002)
    messages = _messages(31, start=now - timedelta(hours=2))

    async def loader(chat_id, after):
        assert chat_id == -7002
        assert after is None
        return messages

    async def summarizer(received, config):
        assert received == messages
        assert config is cfg
        return "• Первая тема\n• Вторая тема\n• Третья тема"

    bot = SimpleNamespace(send_message=AsyncMock(), me=SimpleNamespace(username="test_bot"))
    sent = asyncio.run(
        run_digest_cycle(
            bot,
            now=now,
            config=cfg,
            session_factory=session_factory,
            message_loader=loader,
            summarizer=summarizer,
        )
    )

    assert sent == 1
    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == -7002
    assert kwargs["text"].startswith("#итого\n\n• Первая тема")
    assert kwargs["text"].endswith("Присоединиться к боту: https://max.ru/test_bot")

    with session_factory() as session:
        state = session.get(NotifyDigestRow, -7002)
        assert state is not None
        assert state.last_digest_date == date(2026, 9, 21)
        assert state.last_sent_at is not None
        assert state.last_message_at == messages[-1].created_at.replace(tzinfo=None)


def test_send_error_does_not_move_cursor(session_factory) -> None:
    cfg = NotifyConfig(
        timezone="Europe/Moscow",
        digest_hour=20,
        digest_jitter_minutes=0,
        digest_min_new_messages=30,
    )
    now = datetime(2026, 9, 21, 18, 30, tzinfo=UTC)
    _add_chat(session_factory, -7003)
    previous_cursor = now - timedelta(days=1)
    with session_factory() as session:
        session.add(
            NotifyDigestRow(
                chat_id=-7003,
                last_digest_date=date(2026, 9, 20),
                last_message_at=previous_cursor,
            )
        )
        session.commit()

    messages = _messages(31, start=previous_cursor + timedelta(minutes=1))

    async def loader(_chat_id, after):
        assert after == previous_cursor
        return messages

    async def summarizer(_messages, _config):
        return "• Первая тема\n• Вторая тема\n• Третья тема"

    bot = SimpleNamespace(
        send_message=AsyncMock(side_effect=RuntimeError("MAX unavailable")),
        me=SimpleNamespace(username="test_bot"),
    )
    sent = asyncio.run(
        run_digest_cycle(
            bot,
            now=now,
            config=cfg,
            session_factory=session_factory,
            message_loader=loader,
            summarizer=summarizer,
        )
    )

    assert sent == 0
    with session_factory() as session:
        state = session.get(NotifyDigestRow, -7003)
        assert state is not None
        assert state.last_digest_date == date(2026, 9, 20)
        assert state.last_message_at == previous_cursor.replace(tzinfo=None)


def test_next_day_uses_last_summarized_message_as_cursor(session_factory) -> None:
    cfg = NotifyConfig(
        timezone="Europe/Moscow",
        digest_hour=20,
        digest_jitter_minutes=0,
        digest_min_new_messages=30,
    )
    first_now = datetime(2026, 9, 21, 18, 30, tzinfo=UTC)
    _add_chat(session_factory, -7004)
    messages = _messages(31, start=first_now - timedelta(hours=2))
    seen_after: list[datetime | None] = []

    async def loader(_chat_id, after):
        seen_after.append(after)
        return messages if len(seen_after) == 1 else []

    async def summarizer(_messages, _config):
        return "• Первая тема\n• Вторая тема\n• Третья тема"

    bot = SimpleNamespace(send_message=AsyncMock(), me=SimpleNamespace(username="test_bot"))
    first_sent = asyncio.run(
        run_digest_cycle(
            bot,
            now=first_now,
            config=cfg,
            session_factory=session_factory,
            message_loader=loader,
            summarizer=summarizer,
        )
    )
    second_sent = asyncio.run(
        run_digest_cycle(
            bot,
            now=first_now + timedelta(days=1),
            config=cfg,
            session_factory=session_factory,
            message_loader=loader,
            summarizer=summarizer,
        )
    )

    assert first_sent == 1
    assert second_sent == 0
    assert seen_after == [None, messages[-1].created_at]
    bot.send_message.assert_awaited_once()


def test_template_digest_is_extractive_and_short() -> None:
    now = datetime(2026, 9, 21, 18, tzinfo=UTC)
    messages = _messages(8, start=now)

    text = build_template_digest(messages)

    assert text is not None
    assert text.count("\n") == 4
    assert "Сообщение 3" in text
    assert "Сообщение 7" in text
    assert "Сообщение 0" not in text


def test_disabled_worker_does_not_touch_bot(monkeypatch) -> None:
    import notify.worker as worker_module

    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: SimpleNamespace(notify=NotifyConfig(enabled=False)),
    )
    monkeypatch.setattr(
        worker_module,
        "get_max_bot",
        lambda: (_ for _ in ()).throw(AssertionError("MAX bot не должен запрашиваться")),
    )

    asyncio.run(run_notify_worker())

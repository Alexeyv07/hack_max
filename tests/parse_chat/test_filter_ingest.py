"""Тесты KAN-10 parse_chat: permissive filter + images + geo."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from address.db.address import AddressRow
from events.models.event import EventSource
from parse_chat.handlers.filter import (
    FilterConfig,
    FilterRejectReason,
    FloodTracker,
    filter_message,
)
from parse_chat.handlers.ingest import (
    make_source_msg_id,
    message_to_candidate,
    persist_chat_message,
)
from parse_chat.handlers.media import extract_image_url
from parse_chat.handlers.process import extract_raw_chat_message, process_chat_event
from parse_chat.models.message import RawChatMessage
from parser_common.models.draft import EventDraft
from project.config import reset_settings_cache
from user_chat.db.chat import ChatRow
from user_chat.handlers import create_chat
from user_chat.models.chat import ChatCreate


def _addr(session, *, house: str = "1", street: str = "улица Chat Parse") -> AddressRow:
    row = AddressRow(
        address_text=f"Москва, {street}, д. {house}",
        city="Москва",
        street=street,
        house=house,
        postal_code="125047",
        latitude=Decimal("55.78"),
        longitude=Decimal("37.59"),
    )
    session.add(row)
    session.flush()
    return row


def _msg(
    text: str,
    *,
    chat_id: int = 1001,
    mid: str = "mid-1",
    sender_id: int = 42,
    is_bot: bool = False,
    has_attachments: bool = False,
    image_url: str | None = None,
) -> RawChatMessage:
    return RawChatMessage(
        chat_id=chat_id,
        message_id=mid,
        text=text,
        sender_user_id=sender_id,
        sender_is_bot=is_bot,
        published_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
        has_attachments=has_attachments,
        image_url=image_url,
    )


def _cfg(**kwargs) -> FilterConfig:
    base = dict(min_chars=3, flood_window_seconds=90, flood_max_repeats=3)
    base.update(kwargs)
    return FilterConfig(**base)


def test_text_without_photo_not_dropped() -> None:
    verdict = filter_message(
        _msg("Соседи, кто знает график отключения горячей воды на неделю?"),
        _cfg(),
        flood=FloodTracker(),
    )
    assert verdict.accepted
    assert verdict.signal == "text"
    assert _msg("без фото").image_url is None


def test_pending_photo_attaches_to_next_text() -> None:
    from parse_chat.handlers.pending_photo import PendingPhotoBuffer, apply_pending_photo

    buf = PendingPhotoBuffer()
    photo = _msg(
        "",
        mid="p1",
        sender_id=7,
        image_url="https://cdn.example/yard.jpg",
    )
    held, action = apply_pending_photo(photo, buffer=buf, window_seconds=600, now=1.0)
    assert action == "hold_photo"
    assert held.image_url

    text = _msg("Вот яма у второго подъезда", mid="t1", sender_id=7)
    bound, action2 = apply_pending_photo(text, buffer=buf, window_seconds=600, now=2.0)
    assert action2 == "attached"
    assert bound.image_url == "https://cdn.example/yard.jpg"


def test_pending_photo_not_stolen_by_other_user() -> None:
    from parse_chat.handlers.pending_photo import PendingPhotoBuffer, apply_pending_photo

    buf = PendingPhotoBuffer()
    apply_pending_photo(
        _msg("", mid="p1", sender_id=1, image_url="https://cdn.example/a.jpg"),
        buffer=buf,
        now=1.0,
    )
    other, action = apply_pending_photo(
        _msg("Чужой текст", mid="t2", sender_id=2),
        buffer=buf,
        now=2.0,
    )
    assert action == "passthrough"
    assert other.image_url is None

    text = (
        "Мне кажется, дворовую парковку лучше сделать платную для гостей, "
        "иначе по вечерам жильцам негде поставить машины"
    )
    verdict = filter_message(_msg(text), _cfg(), flood=FloodTracker())
    assert verdict.accepted
    assert verdict.signal == "text"


def test_filter_accepts_short_newsy() -> None:
    verdict = filter_message(
        _msg("Во дворе снова яма после дождя"),
        _cfg(),
        flood=FloodTracker(),
    )
    assert verdict.accepted


def test_filter_rejects_bot_command_greeting() -> None:
    flood = FloodTracker()
    assert filter_message(_msg("/start"), _cfg(), flood=flood).reason == (
        FilterRejectReason.COMMAND
    )
    assert filter_message(_msg("привет"), _cfg(), flood=flood).reason == (
        FilterRejectReason.GREETING_ONLY
    )
    assert (
        filter_message(
            _msg("", has_attachments=True),
            _cfg(),
            flood=flood,
        ).reason
        == FilterRejectReason.STICKER_ONLY
    )


def test_filter_greeting_inside_long_text_ok() -> None:
    verdict = filter_message(
        _msg("Привет соседи, кто знает когда починят лифт в 2 подъезде?"),
        _cfg(),
        flood=FloodTracker(),
    )
    assert verdict.accepted


def test_filter_accepts_image_only_when_not_held() -> None:
    # filter сам по себе принимает; hold делается в process/apply_pending_photo
    verdict = filter_message(
        _msg("", image_url="https://cdn.example/photo.jpg"),
        _cfg(),
        flood=FloodTracker(),
    )
    assert verdict.accepted
    assert verdict.signal == "image"


def test_filter_flood_repeat() -> None:
    flood = FloodTracker()
    cfg = _cfg(flood_max_repeats=2)
    text = "Снова лужа у подъезда после дождя"
    assert filter_message(_msg(text, mid="a"), cfg, flood=flood, now=1.0).accepted
    assert filter_message(_msg(text, mid="b"), cfg, flood=flood, now=2.0).accepted
    third = filter_message(_msg(text, mid="c"), cfg, flood=flood, now=3.0)
    assert not third.accepted
    assert third.reason == FilterRejectReason.FLOOD


def test_extract_image_url_from_attachment() -> None:
    att = SimpleNamespace(
        type="image",
        payload=SimpleNamespace(
            photo_id=1,
            token="t",
            url="https://cdn.max.ru/photos/abc.jpg",
        ),
    )
    assert extract_image_url([att]) == "https://cdn.max.ru/photos/abc.jpg"
    sticker = SimpleNamespace(
        type="sticker", payload=SimpleNamespace(url="https://x/st.webp", code="1")
    )
    assert extract_image_url([sticker]) is None


def test_extract_raw_includes_image() -> None:
    event = SimpleNamespace(
        message=SimpleNamespace(
            recipient=SimpleNamespace(chat_id=10, chat_type="chat"),
            body=SimpleNamespace(
                mid="m-img",
                text="Смотрите что во дворе",
                attachments=[
                    SimpleNamespace(
                        type="image",
                        payload=SimpleNamespace(
                            photo_id=9,
                            token="tok",
                            url="https://cdn.max.ru/p/1.jpg",
                        ),
                    )
                ],
            ),
            sender=SimpleNamespace(user_id=5, is_bot=False),
            timestamp=1_700_000_000_000,
        )
    )
    raw = extract_raw_chat_message(event)
    assert raw is not None
    assert raw.image_url == "https://cdn.max.ru/p/1.jpg"
    assert "дворе" in raw.text


def test_extract_raw_skips_dialog() -> None:
    event = SimpleNamespace(
        message=SimpleNamespace(
            recipient=SimpleNamespace(chat_id=1, chat_type="dialog"),
            body=SimpleNamespace(mid="m1", text="отключили воду", attachments=None),
            sender=SimpleNamespace(user_id=5, is_bot=False),
            timestamp=1_700_000_000_000,
        )
    )
    assert extract_raw_chat_message(event) is None


def test_message_to_candidate_keeps_image() -> None:
    cand = message_to_candidate(_msg("Фото ямы", image_url="https://cdn.example/a.jpg"))
    assert cand.image_url == "https://cdn.example/a.jpg"
    assert cand.address_id is None


def test_persist_passes_image_url(db_session) -> None:
    addr = _addr(db_session)
    create_chat(
        db_session,
        ChatCreate(chat_id=555, address_id=addr.id, title="Дом 1", chat_type="chat"),
    )
    msg = _msg(
        "Яма у подъезда",
        chat_id=555,
        mid="img-1",
        image_url="https://cdn.example/hole.jpg",
    )
    with patch(
        "parse_chat.handlers.ingest.normalize",
        return_value=EventDraft(
            title="Яма",
            body=msg.text,
            importance=2,
            source=EventSource.NEIGHBORS_CHAT.value,
            source_msg_id=make_source_msg_id(555, "img-1"),
            address_id=None,
            image_url=msg.image_url,
        ),
    ):
        event = persist_chat_message(db_session, msg)
    assert event is not None
    assert event.image_url == "https://cdn.example/hole.jpg"
    assert event.address_id == addr.id


def test_process_chat_event_end_to_end(db_session, monkeypatch) -> None:
    addr = _addr(db_session, house="7")
    create_chat(
        db_session,
        ChatCreate(chat_id=777, address_id=addr.id, title="Дом 7", chat_type="chat"),
    )

    from contextlib import contextmanager

    @contextmanager
    def _fake_scope():
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    monkeypatch.setattr("parse_chat.handlers.process.session_scope", _fake_scope)
    monkeypatch.setenv("ENABLE_CHAT_PARSER", "true")
    reset_settings_cache()

    event = SimpleNamespace(
        message=SimpleNamespace(
            recipient=SimpleNamespace(chat_id=777, chat_type="chat"),
            body=SimpleNamespace(
                mid="e2e-1",
                text="Интересное мнение: лучше бы сделали детскую площадку вместо парковки",
                attachments=None,
            ),
            sender=SimpleNamespace(user_id=9, is_bot=False),
            timestamp=1_700_000_000_000,
        )
    )
    monkeypatch.setattr(
        "parse_chat.handlers.process.get_settings",
        lambda: SimpleNamespace(
            runtime=SimpleNamespace(enable_chat_parser=True),
            chat_parser=SimpleNamespace(
                enabled=True,
                min_chars=3,
                flood_window_seconds=90,
                flood_max_repeats=3,
                greeting_only=("привет",),
            ),
        ),
    )

    assert process_chat_event(event) is True
    assert process_chat_event(event) is False


def test_skips_unknown_chat(db_session) -> None:
    msg = _msg("Отключили воду в подъезде на весь день", chat_id=99999, mid="x")
    assert persist_chat_message(db_session, msg) is None
    assert db_session.get(ChatRow, 99999) is None

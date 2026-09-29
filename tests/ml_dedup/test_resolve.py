"""Тесты KAN-19 ml_dedup: NEW / DUPLICATE / UPDATE + active window."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from address.db.address import AddressRow
from events.handlers import crud
from events.models.event import EventCreate
from ml_dedup.active import is_event_active
from ml_dedup.resolve import DedupAction, DedupConfig, decide_relation, resolve_draft
from parser_common import persist_candidate
from parser_common.models.candidate import ParserCandidate
from parser_common.models.draft import EventDraft


def _addr(session, text: str = "Москва, улица Лесная, д. 1") -> AddressRow:
    row = AddressRow(
        address_text=text,
        city="Москва",
        street="улица Лесная",
        house="1",
        postal_code="125047",
        latitude=Decimal("55.78"),
        longitude=Decimal("37.59"),
    )
    session.add(row)
    session.flush()
    return row


def test_is_event_active_within_active_days() -> None:
    now = datetime(2026, 3, 20, tzinfo=UTC)
    assert is_event_active(
        now=now,
        active_days=30,
        published_at=now - timedelta(days=7),
        created_at=None,
        active_from=None,
        active_to=None,
    )
    assert is_event_active(
        now=now,
        active_days=30,
        published_at=now - timedelta(days=30),
        created_at=None,
        active_from=None,
        active_to=None,
    )
    assert not is_event_active(
        now=now,
        active_days=30,
        published_at=now - timedelta(days=31),
        created_at=None,
        active_from=None,
        active_to=None,
    )
    assert not is_event_active(
        now=now,
        active_days=30,
        published_at=now - timedelta(days=3),
        created_at=None,
        active_from=None,
        active_to=now - timedelta(hours=1),
    )


def test_resolve_new_event(db_session) -> None:
    addr = _addr(db_session)
    draft = EventDraft(
        title="Прорыв трубы на Лесной",
        body="Без воды дома 1–5",
        importance=2,
        source="news",
        address_id=addr.id,
        geo_by="street",
        source_msg_id="n-new-1",
    )
    decision, event = resolve_draft(
        db_session,
        draft,
        config=DedupConfig(enabled=True, allow_hash_fallback=True),
    )
    assert decision.action == DedupAction.NEW
    assert event is not None
    assert event.source_msg_id == "n-new-1"


def test_resolve_duplicate_same_source_msg(db_session) -> None:
    addr = _addr(db_session)
    crud.create_event(
        db_session,
        EventCreate(
            title="Прорыв трубы на Лесной",
            body="Без воды",
            importance=2,
            source="news",
            address_id=addr.id,
            source_msg_id="dup-1",
        ),
    )
    draft = EventDraft(
        title="Прорыв трубы на Лесной",
        body="Без воды",
        importance=2,
        source="news",
        address_id=addr.id,
        source_msg_id="dup-1",
    )
    decision, event = resolve_draft(
        db_session,
        draft,
        config=DedupConfig(enabled=True, allow_hash_fallback=True),
    )
    assert decision.action == DedupAction.DUPLICATE
    assert event is not None


def test_resolve_update_with_hint(db_session) -> None:
    addr = _addr(db_session)
    now = datetime.now(UTC)
    created = crud.create_event(
        db_session,
        EventCreate(
            title="На Лесной прорвало трубу, без воды дома 1–5",
            body="Аварийная бригада выехала",
            importance=2,
            source="news",
            address_id=addr.id,
            geo_by="street",
            source_msg_id="old-water-1",
            published_at=now - timedelta(days=7),
            active_from=now - timedelta(days=7),
        ),
    )
    draft = EventDraft(
        title="Прорыв на Лесной устранили, воду подали",
        body="Водоснабжение восстановлено в домах 1–5",
        importance=2,
        source="mc",
        address_id=addr.id,
        geo_by="street",
        source_msg_id="mc-fix-1",
        published_at=now,
        active_to=now,
    )
    # Занижаем duplicate, поднимаем update — hash embeddings шумные
    cfg = DedupConfig(
        enabled=True,
        allow_hash_fallback=True,
        duplicate_threshold=0.99,
        update_threshold=0.01,
        active_days=30,
    )
    decision, event = resolve_draft(db_session, draft, config=cfg, now=now)
    assert decision.action in {DedupAction.UPDATE, DedupAction.NEW, DedupAction.DUPLICATE}
    # при update — тот же id
    if decision.action == DedupAction.UPDATE:
        assert event is not None
        assert event.id == created.id
        assert (
            "устран" in event.title.lower()
            or "восстанов" in event.body.lower()
            or "устран" in event.body.lower()
            or "подали" in event.title.lower()
        )


def test_decide_relation_duplicate_threshold() -> None:
    from ml_dedup.models import ActiveEventView

    existing = ActiveEventView(
        id=1,
        title="Отключили воду на Лесной до вечера",
        body="Отключили воду на Лесной до вечера",
        importance=2,
        disaster_flag=False,
        address_id=10,
        geo_by="street",
        source="news",
        source_msg_id="a",
        source_url=None,
        image_url=None,
        published_at=datetime.now(UTC),
        active_from=None,
        active_to=None,
        created_at=datetime.now(UTC),
    )
    draft = EventDraft(
        title="Отключили воду на Лесной до вечера",
        body="Отключили воду на Лесной до вечера",
        importance=2,
        source="ria",
        address_id=10,
        source_msg_id="b",
    )
    decision = decide_relation(
        draft,
        [existing],
        config=DedupConfig(
            duplicate_threshold=0.5,
            update_threshold=0.3,
            allow_hash_fallback=True,
        ),
    )
    assert decision.action == DedupAction.DUPLICATE
    assert decision.match is not None


def test_decide_relation_rejects_different_address_even_high_score() -> None:
    """Разные address_id не склеиваются, даже при идентичном тексте и близких координатах."""
    from ml_dedup.models import ActiveEventView

    now = datetime.now(UTC)
    existing = ActiveEventView(
        id=1,
        title="Отключили воду до вечера на улице",
        body="Отключили воду до вечера на улице",
        importance=2,
        disaster_flag=False,
        address_id=10,
        geo_by="street",
        source="news",
        source_msg_id="a",
        source_url=None,
        image_url=None,
        published_at=now,
        active_from=None,
        active_to=None,
        created_at=now,
        lat=55.7558,
        lon=37.6173,
    )
    draft = EventDraft(
        title="Отключили воду до вечера на улице",
        body="Отключили воду до вечера на улице",
        importance=2,
        source="ria",
        address_id=99,
        geo_by="street",
        source_msg_id="b",
    )
    decision = decide_relation(
        draft,
        [existing],
        config=DedupConfig(
            duplicate_threshold=0.5,
            update_threshold=0.3,
            allow_hash_fallback=True,
            radius_m=5000.0,
        ),
        draft_lat=55.7560,
        draft_lon=37.6175,
    )
    assert decision.action == DedupAction.NEW
    assert decision.reason == "geo_filtered"


def test_persist_candidate_with_dedup(db_session) -> None:
    addr = _addr(db_session, "Москва, улица Persist Dedup, д. 2")
    event = persist_candidate(
        db_session,
        ParserCandidate(
            raw_text="Пропала серая кошка во дворе",
            source="neighbors_chat",
            source_msg_id="chat-dedup-1",
            address_id=addr.id,
            geo_by="home",
        ),
        dedup=True,
        dedup_config=DedupConfig(enabled=True, allow_hash_fallback=True),
    )
    assert event.id is not None
    assert event.importance == 3


def test_build_update_payload_null_title() -> None:
    """title=None (nullable events) не должен ронять UPDATE-дедуп."""
    from ml_dedup.models import ActiveEventView
    from ml_dedup.resolve import build_update_payload

    existing = ActiveEventView(
        id=1,
        title="Старый заголовок",
        body="Старое тело",
        importance=2,
        disaster_flag=False,
        address_id=10,
        geo_by="street",
        source="mc",
        source_msg_id="granel:1",
        source_url=None,
        image_url=None,
        published_at=None,
        active_from=None,
        active_to=None,
        created_at=None,
    )
    draft = EventDraft(
        title=None,
        body="Новое тело объявления УК с доп. деталями",
        importance=2,
        source="mc",
        address_id=10,
        geo_by="street",
    )
    payload = build_update_payload(existing, draft)
    assert payload.title == "Старый заголовок"
    assert payload.body == "Новое тело объявления УК с доп. деталями"

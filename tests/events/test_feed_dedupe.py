"""Дедуп карточек ленты (MC :addr: + title/body)."""

from __future__ import annotations

from datetime import UTC, datetime

from events.feed_dedupe import content_group_key, dedupe_feed_events, sibling_group_key
from events.models.event import Event


def _event(
    *,
    event_id: int,
    title: str | None,
    body: str,
    source: str = "mc",
    source_msg_id: str | None = None,
    weight: float = 1.0,
    distance_m: float | None = None,
) -> Event:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    return Event(
        id=event_id,
        title=title,
        body=body,
        importance=1,
        source=source,
        address_id=event_id,
        lat=55.75,
        lon=37.61,
        weight=weight,
        source_msg_id=source_msg_id,
        disaster_flag=False,
        source_url=None,
        image_url=None,
        geo_by="street",
        published_at=now,
        created_at=now,
        updated_at=now,
        distance_m=distance_m,
    )


def test_sibling_group_key_strips_addr_suffix() -> None:
    assert sibling_group_key(source="mc", source_msg_id="zhil:1:addr:42") == "mc|zhil:1"
    assert sibling_group_key(source="mc", source_msg_id="zhil:1") == "mc|zhil:1"


def test_content_group_key_prefers_title() -> None:
    assert content_group_key(title="Отключение горячей воды", body="x") == (
        "t:отключение горячей воды"
    )


def test_dedupe_mc_addr_fanout_keeps_nearest() -> None:
    a = _event(
        event_id=1,
        title="Отключение ГВС на Тверской",
        body="работники",
        source_msg_id="zhil:9:addr:10",
        distance_m=800,
        weight=0.5,
    )
    b = _event(
        event_id=2,
        title="Отключение ГВС на Тверской",
        body="работники",
        source_msg_id="zhil:9:addr:20",
        distance_m=200,
        weight=0.4,
    )
    c = _event(
        event_id=3,
        title="Другое событие рядом",
        body="совсем другой текст про аварию длинный чтобы ключ сработал если title короткий",
        source_msg_id="news:1",
        source="news",
        distance_m=100,
        weight=0.9,
    )
    out = dedupe_feed_events([a, b, c], prefer="distance")
    assert [e.id for e in out] == [2, 3]


def test_dedupe_same_title_different_sources() -> None:
    a = _event(
        event_id=1,
        title="Пожар на Арбате сегодня утром",
        body="детали a",
        source="news",
        source_msg_id="ria:1",
        weight=0.8,
    )
    b = _event(
        event_id=2,
        title="Пожар на Арбате сегодня утром",
        body="детали b",
        source="news",
        source_msg_id="tass:2",
        weight=0.9,
    )
    out = dedupe_feed_events([a, b], prefer="weight")
    assert [e.id for e in out] == [2]

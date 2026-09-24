"""Офлайн-тесты persist / fan-out УК-объявлений."""

from __future__ import annotations

from datetime import UTC, datetime

from address.db.address import AddressRow
from address.resolve import GeoBind, GeoByLevel
from events.models.event import EventSource
from parse_mc.handlers.ingest import persist_notice
from parse_mc.models.notice import RawMcNotice


def _notice(*, external_id: str = "42") -> RawMcNotice:
    return RawMcNotice(
        outlet="zhil_nagatino",
        external_id=external_id,
        url=f"https://www.gbuns.ru/organizacia/novosti/9-news/{external_id}-test",
        title="Отключение горячей воды",
        published_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
        body="По адресам: ул. Тверская и Варшавское шоссе.",
        streets=("Тверская", "Варшавское шоссе"),
        geo_city="Москва",
    )


def test_persist_notice_skips_without_geo(db_session) -> None:
    notice = _notice(external_id="100")
    assert persist_notice(db_session, notice, geos=None) == []
    assert persist_notice(db_session, notice, geos=[]) == []


def test_persist_notice_single(db_session) -> None:
    addr = AddressRow(
        address_text="Москва, город",
        city="Москва",
        latitude=55.75,
        longitude=37.61,
    )
    db_session.add(addr)
    db_session.flush()

    notice = _notice(external_id="100")
    events = persist_notice(
        db_session,
        notice,
        geos=[GeoBind(address_id=addr.id, geo_by=GeoByLevel.CITY)],
    )
    assert len(events) == 1
    assert events[0].source == EventSource.MC.value
    assert events[0].source_msg_id == "zhil_nagatino:100"
    assert events[0].address_id == addr.id


def test_persist_notice_fanout_per_street(db_session) -> None:
    a1 = AddressRow(
        address_text="Москва, ул. Тверская",
        city="Москва",
        street="ул. Тверская",
        latitude=55.75,
        longitude=37.61,
    )
    a2 = AddressRow(
        address_text="Москва, Варшавское шоссе",
        city="Москва",
        street="Варшавское шоссе",
        latitude=55.65,
        longitude=37.62,
    )
    db_session.add_all([a1, a2])
    db_session.flush()

    notice = _notice(external_id="200")
    geos = [
        GeoBind(address_id=a1.id, geo_by=GeoByLevel.STREET),
        GeoBind(address_id=a2.id, geo_by=GeoByLevel.STREET),
    ]
    events = persist_notice(db_session, notice, geos=geos)
    assert len(events) == 2
    msg_ids = {e.source_msg_id for e in events}
    assert msg_ids == {
        f"zhil_nagatino:200:addr:{a1.id}",
        f"zhil_nagatino:200:addr:{a2.id}",
    }
    assert {e.address_id for e in events} == {a1.id, a2.id}

    again = persist_notice(db_session, notice, geos=geos)
    assert again == []

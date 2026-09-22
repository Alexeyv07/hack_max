"""Unit-smoke для ru_window (разметка, не runtime)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ru_window import extract_window, looks_like_no_window

_MSK = timezone(timedelta(hours=3))


def test_gvs_full_range() -> None:
    ref = datetime(2026, 7, 22, 12, 0, tzinfo=_MSK)
    text = (
        "Внимание! отключении услуги ГВС с 23.07.2026 10:00:00 на мкд\n"
        "Планируемое время включения 27.07.2026 18:00:00 — работы проводит УСТЭК"
    )
    w = extract_window(text, ref)
    assert w is not None
    assert w.active_from is not None and w.active_to is not None
    assert w.active_from.day == 23 and w.active_from.hour == 10
    assert w.active_to.day == 27 and w.active_to.hour == 18


def test_opressovka_dash() -> None:
    ref = datetime(2026, 7, 6, 12, 0, tzinfo=_MSK)
    w = extract_window("График опрессовки: 7 - 21 июля 2026 г. Отключение ГВС.", ref)
    assert w is not None
    assert w.active_from is not None and w.active_to is not None
    assert w.active_from.day == 7 and w.active_to.day == 21


def test_tomorrow_tractor() -> None:
    ref = datetime(2026, 2, 2, 15, 53, tzinfo=_MSK)
    w = extract_window("Горького 32 завтра в 8.15 приедет трактор чистить снег", ref)
    assert w is not None
    assert w.active_from is not None
    assert w.active_from.day == 3 and w.active_from.hour == 8


def test_payment_not_window() -> None:
    ref = datetime(2026, 9, 10, 12, 0, tzinfo=_MSK)
    w = extract_window(
        "Напоминаем: сделать оплату коммунальных услуг необходимо до 15 сентября.",
        ref,
    )
    assert w is None
    assert looks_like_no_window("Счета за март уже доступны в приложении «Госуслуги Дом»")

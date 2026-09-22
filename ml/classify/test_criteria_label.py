"""Smoke-тесты criteria_label (пограничные кейсы из инструкции)."""

from __future__ import annotations

import sys
from pathlib import Path

from criteria_label import label_text

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def test_border_outage_is_2() -> None:
    d = label_text("Завтра отключат воду до вечера")
    assert d.importance == 2 and not d.skip


def test_border_active_flood_is_1() -> None:
    d = label_text("Прорвало стояк, вода сейчас заливает квартиры")
    assert d.importance == 1 and not d.disaster_flag


def test_border_resolved_fire_is_3() -> None:
    d = label_text("Вчера был пожар, полностью потушен, ограничений нет")
    assert d.importance == 3


def test_border_evac_after_fire_is_1() -> None:
    d = label_text("После пожара запрещён вход в секцию, организована эвакуация")
    assert d.importance == 1


def test_border_lift_people_is_1() -> None:
    d = label_text("В лифте застряли люди, нужна помощь")
    assert d.importance == 1


def test_border_empty_lift_is_2() -> None:
    d = label_text("Лифт не работает, кабина пустая")
    assert d.importance == 2


def test_border_cat_is_3() -> None:
    d = label_text("Пропал кот")
    assert d.importance == 3


def test_gas_smell_is_1() -> None:
    d = label_text("Житель сообщает о запахе газа в доме")
    assert d.importance == 1 and not d.disaster_flag

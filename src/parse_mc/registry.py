"""Реестр адаптеров УК/ЖЭК."""

from __future__ import annotations

from parse_mc.sources.base import McSource
from parse_mc.sources.gbu_portal import GbuPortalSource
from parse_mc.sources.granel import GranelSource
from parse_mc.sources.moek import MoekSource
from parse_mc.sources.pik_comfort import PikComfortSource
from parse_mc.sources.zhil_nagatino import ZhilNagatinoSource
from project.config import McParserConfig, McSourceConfig


def get_sources(cfg: McParserConfig) -> list[McSource]:
    builders: list[tuple[str, type]] = [
        ("pik_comfort", PikComfortSource),
        ("granel", GranelSource),
        ("zhil_nagatino", ZhilNagatinoSource),
        ("gbu_portal", GbuPortalSource),
        ("moek", MoekSource),
    ]
    out: list[McSource] = []
    for key, cls in builders:
        source_cfg = cfg.sources.get(key) or McSourceConfig()
        if not source_cfg.enabled:
            continue
        out.append(cls(source_cfg))
    return out

"""Реестр адаптеров источников новостей."""

from __future__ import annotations

from parse_news.sources.base import NewsSource
from parse_news.sources.kommersant import KommersantSource
from parse_news.sources.m24 import M24Source
from parse_news.sources.msk1 import Msk1Source
from parse_news.sources.mskagency import MskagencySource
from parse_news.sources.ria import RiaSource
from parse_news.sources.tass import TassSource
from project.config import NewsParserConfig, NewsSourceConfig


def get_sources(cfg: NewsParserConfig) -> list[NewsSource]:
    builders: list[tuple[str, type]] = [
        ("tass", TassSource),
        ("ria", RiaSource),
        ("kommersant", KommersantSource),
        ("msk1", Msk1Source),
        ("mskagency", MskagencySource),
        ("m24", M24Source),
    ]
    out: list[NewsSource] = []
    for key, cls in builders:
        source_cfg = cfg.sources.get(key) or NewsSourceConfig()
        if not source_cfg.enabled:
            continue
        out.append(cls(source_cfg))
    return out

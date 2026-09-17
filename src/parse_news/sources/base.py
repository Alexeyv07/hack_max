"""Базовый контракт адаптера источника новостей."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

import httpx

from parse_news.models.article import RawNewsArticle

CollectMode = Literal["backfill", "incremental"]


@dataclass(frozen=True, slots=True)
class CollectResult:
    articles: list[RawNewsArticle]
    next_cursor: str | None
    reached_since: bool


class NewsSource(Protocol):
    key: str

    async def collect(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        mode: CollectMode,
        listing_cursor: str | None,
        max_articles: int,
    ) -> CollectResult: ...


class BaseNewsSource(ABC):
    key: str

    @abstractmethod
    async def collect(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        mode: CollectMode,
        listing_cursor: str | None,
        max_articles: int,
    ) -> CollectResult: ...

"""Базовый контракт адаптера источника УК/ЖЭК."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

import httpx

from parse_mc.models.notice import RawMcNotice

CollectMode = Literal["backfill", "incremental"]


@dataclass(frozen=True, slots=True)
class CollectResult:
    notices: list[RawMcNotice]
    next_cursor: str | None
    reached_since: bool


class McSource(Protocol):
    key: str

    async def collect(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        mode: CollectMode,
        listing_cursor: str | None,
        max_articles: int,
        max_pages: int = 5,
    ) -> CollectResult: ...


class BaseMcSource(ABC):
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
        max_pages: int = 5,
    ) -> CollectResult: ...

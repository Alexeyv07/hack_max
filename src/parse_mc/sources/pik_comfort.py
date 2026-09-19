"""Адаптер ПИК-Комфорт (pik-comfort.ru/news*)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx

from parse_mc.models.notice import RawMcNotice
from parse_mc.sources.base import BaseMcSource, CollectMode, CollectResult
from parse_mc.sources.common import (
    dedupe_notices,
    enrich_url,
    ensure_aware,
    find_links,
    stable_id,
)
from parser_common.http import fetch_text
from project.config import McSourceConfig
from project.logging_setup import get_logger

logger = get_logger(__name__)

_DEFAULT_LISTING = "https://pik-comfort.ru/news_all"
_NEWS_LINK = re.compile(r"/news(?:_all|\d+)$|/news\d+")
_ID_RE = re.compile(r"/news(\d+)$")


class PikComfortSource(BaseMcSource):
    key = "pik_comfort"

    def __init__(self, cfg: McSourceConfig | None = None) -> None:
        self.cfg = cfg or McSourceConfig()

    async def collect(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        mode: CollectMode,
        listing_cursor: str | None,
        max_articles: int,
        max_pages: int = 5,
    ) -> CollectResult:
        listing = self.cfg.listing_url or _DEFAULT_LISTING
        try:
            html = await fetch_text(client, listing)
        except httpx.HTTPError as exc:
            logger.error("pik_comfort listing: %s", exc)
            raise

        links = find_links(html, base_url=listing, href_pattern=_NEWS_LINK)
        notices: list[RawMcNotice] = []
        for url, title in links:
            if "/news_all" in url:
                continue
            if len(notices) >= max_articles:
                break
            m = _ID_RE.search(url.rstrip("/"))
            external_id = m.group(1) if m else stable_id(url)
            notice = await enrich_url(
                client,
                url,
                outlet=self.key,
                external_id=external_id,
                fallback_title=title,
                fallback_published=datetime.now(UTC),
            )
            if notice is None:
                continue
            published = ensure_aware(notice.published_at) or datetime.now(UTC)
            if published < since and mode == "backfill":
                continue
            notices.append(notice)

        notices.sort(key=lambda n: n.published_at, reverse=True)
        return CollectResult(
            notices=dedupe_notices(notices),
            next_cursor=None,
            reached_since=True,
        )

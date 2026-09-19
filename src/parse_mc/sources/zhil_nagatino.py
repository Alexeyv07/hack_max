"""Адаптер ГБУ «Жилищник района Нагатино-Садовники» (gbuns.ru)."""

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
    parse_ru_date,
    stable_id,
)
from parser_common.http import fetch_text
from project.config import McSourceConfig
from project.logging_setup import get_logger

logger = get_logger(__name__)

_DEFAULT_LISTING = "https://www.gbuns.ru/organizacia/novosti"
_NEWS_LINK = re.compile(r"/organizacia/novosti/\d+-news/\d+-[a-z0-9\-]+", re.I)
_ID_RE = re.compile(r"/(\d+)-[a-z0-9\-]+/?$", re.I)


class ZhilNagatinoSource(BaseMcSource):
    key = "zhil_nagatino"

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
        start_page = 1
        if mode == "backfill" and listing_cursor and listing_cursor.isdigit():
            start_page = max(1, int(listing_cursor))
        page_limit = 1 if mode == "incremental" else max_pages

        notices: list[RawMcNotice] = []
        reached_since = False
        next_cursor: str | None = None
        page = start_page
        pages_done = 0

        while pages_done < page_limit and len(notices) < max_articles:
            url = listing if page <= 1 else f"{listing}?start={(page - 1) * 10}"
            try:
                html = await fetch_text(client, url)
            except httpx.HTTPError as exc:
                logger.error("zhil_nagatino listing %s: %s", url, exc)
                if pages_done == 0:
                    raise
                break
            pages_done += 1
            links = find_links(html, base_url=url, href_pattern=_NEWS_LINK)
            if not links:
                reached_since = True
                break

            hit_cap = False
            for article_url, title in links:
                if len(notices) >= max_articles:
                    hit_cap = True
                    next_cursor = str(page)
                    break
                m = _ID_RE.search(article_url)
                external_id = m.group(1) if m else stable_id(article_url)
                fallback_published = parse_ru_date(title) or datetime.now(UTC)
                notice = await enrich_url(
                    client,
                    article_url,
                    outlet=self.key,
                    external_id=external_id,
                    fallback_title=_strip_leading_date(title),
                    fallback_published=fallback_published,
                )
                if notice is None:
                    continue
                published = ensure_aware(notice.published_at) or datetime.now(UTC)
                if published < since:
                    reached_since = True
                    continue
                notices.append(notice)

            if hit_cap or reached_since:
                break
            page += 1

        if next_cursor is None and not reached_since and len(notices) >= max_articles:
            next_cursor = str(page)

        notices.sort(key=lambda n: n.published_at, reverse=True)
        return CollectResult(
            notices=dedupe_notices(notices),
            next_cursor=next_cursor,
            reached_since=reached_since or mode == "incremental",
        )


def _strip_leading_date(title: str | None) -> str | None:
    if not title:
        return title
    return (
        re.sub(
            r"^\d{1,2}\s+[а-яё]+\s*,?\s*\d{4}\s+",
            "",
            title,
            flags=re.I,
        ).strip()
        or title
    )

"""Адаптер ПАО «МОЭК» (moek.ru/press/news) — теплосеть / отключения."""

from __future__ import annotations

import calendar
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

_DEFAULT_LISTING = "https://www.moek.ru/press/news/"
_NEWS_LINK = re.compile(r"/press/news/\d{4}/\d{2}/\d+/?", re.I)
_ID_RE = re.compile(r"/press/news/(\d{4})/(\d{2})/(\d+)/?")


class MoekSource(BaseMcSource):
    key = "moek"

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
        # Курсор: YYYY-MM для листания архива по месяцам.
        months = _month_pages(since=since, listing_cursor=listing_cursor, max_pages=max_pages)
        if mode == "incremental":
            months = months[:1]

        notices: list[RawMcNotice] = []
        reached_since = False
        next_cursor: str | None = None

        for idx, (year, month) in enumerate(months):
            url = f"https://www.moek.ru/press/news/{year:04d}/{month:02d}/"
            if idx == 0 and listing.rstrip("/").endswith("/news"):
                # Первая страница — актуальная лента (может отличаться от архива месяца).
                try_urls = [listing, url]
            else:
                try_urls = [url]

            html = None
            for candidate in try_urls:
                try:
                    html = await fetch_text(client, candidate)
                    break
                except httpx.HTTPError as exc:
                    logger.warning("moek listing %s: %s", candidate, exc)
            if not html:
                if idx == 0:
                    logger.error("moek listing failed: %s", try_urls)
                    return CollectResult(notices=[], next_cursor=None, reached_since=True)
                reached_since = True
                break

            links = find_links(html, base_url=url, href_pattern=_NEWS_LINK)
            page_hit_cap = False
            for article_url, title in links:
                if len(notices) >= max_articles:
                    page_hit_cap = True
                    next_cursor = f"{year:04d}-{month:02d}"
                    break
                m = _ID_RE.search(article_url)
                if m:
                    external_id = m.group(3)
                    published_guess = _month_fallback(int(m.group(1)), int(m.group(2)))
                else:
                    external_id = stable_id(article_url)
                    published_guess = _month_fallback(year, month)

                notice = await enrich_url(
                    client,
                    article_url,
                    outlet=self.key,
                    external_id=external_id,
                    fallback_title=title,
                    fallback_published=published_guess,
                )
                if notice is None:
                    continue
                published = ensure_aware(notice.published_at) or published_guess
                # На listing (incremental) берём всё с первой страницы; lookback — только backfill.
                if published < since and mode == "backfill":
                    reached_since = True
                    continue
                notices.append(notice)

            if page_hit_cap:
                break
            if reached_since and mode == "backfill":
                break

        if next_cursor is None and not reached_since and len(months) >= max_pages:
            last_y, last_m = months[-1]
            next_cursor = f"{last_y:04d}-{last_m:02d}"

        notices.sort(key=lambda n: n.published_at, reverse=True)
        return CollectResult(
            notices=dedupe_notices(notices),
            next_cursor=next_cursor,
            reached_since=reached_since or mode == "incremental",
        )


def _month_fallback(year: int, month: int) -> datetime:
    """Конец месяца: day=1 ломал lookback (весь сентябрь < since на 23-е)."""
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, last_day, 12, 0, tzinfo=UTC)


def _month_pages(
    *,
    since: datetime,
    listing_cursor: str | None,
    max_pages: int,
) -> list[tuple[int, int]]:
    now = datetime.now(UTC)
    year, month = now.year, now.month
    if listing_cursor and re.fullmatch(r"\d{4}-\d{2}", listing_cursor):
        year = int(listing_cursor[:4])
        month = int(listing_cursor[5:7])

    since_y, since_m = since.year, since.month
    out: list[tuple[int, int]] = []
    for _ in range(max(1, max_pages)):
        if (year, month) < (since_y, since_m):
            break
        out.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return out

"""Адаптер msk1.ru (RSS + HTML pagination)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx

from parse_news.models.article import RawNewsArticle
from parse_news.sources.base import BaseNewsSource, CollectMode, CollectResult
from parse_news.sources.common import (
    collect_from_rss,
    enrich_url,
    ensure_aware,
    extract_id_from_url,
    find_links,
)
from project.config import NewsSourceConfig
from project.logging_setup import get_logger

logger = get_logger(__name__)

_DEFAULT_FEED = "https://msk1.ru/rss-feeds/rss.xml"
_LISTING_URL = "https://msk1.ru/text/?page={page}"
_TEXT_LINK = re.compile(r"/text/[^/]+/\d{4}/\d{2}/\d{2}/\d+/?")
_URL_DATE = re.compile(r"/text/[^/]+/(\d{4})/(\d{2})/(\d{2})/(\d+)/?")


class Msk1Source(BaseNewsSource):
    key = "msk1"

    def __init__(self, cfg: NewsSourceConfig | None = None) -> None:
        self.cfg = cfg or NewsSourceConfig()

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
        if mode == "incremental":
            return await self._collect_incremental(client, since=since, max_articles=max_articles)
        return await self._collect_backfill(
            client,
            since=since,
            listing_cursor=listing_cursor,
            max_articles=max_articles,
            max_pages=max_pages,
        )

    async def _collect_incremental(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        max_articles: int,
    ) -> CollectResult:
        feed_url = self.cfg.feed_url or _DEFAULT_FEED
        try:
            articles = await collect_from_rss(
                client,
                feed_url,
                outlet=self.key,
                since=since,
                max_articles=max_articles,
            )
        except httpx.HTTPError as exc:
            logger.error("msk1 RSS недоступен %s: %s", feed_url, exc)
            raise
        return CollectResult(articles=articles, next_cursor=None, reached_since=False)

    async def _collect_backfill(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        listing_cursor: str | None,
        max_articles: int,
        max_pages: int,
    ) -> CollectResult:
        page = int(listing_cursor) if listing_cursor and listing_cursor.isdigit() else 1
        articles: list[RawNewsArticle] = []
        reached_since = False
        next_cursor: str | None = None
        pages_done = 0
        seen_ids: set[str] = set()

        while len(articles) < max_articles and pages_done < max_pages:
            page_url = _listing_page_url(self.cfg.listing_url, page)
            status_html = await _fetch_listing(client, page_url)
            if status_html is None:
                reached_since = True
                break
            _, html = status_html
            pages_done += 1

            links = find_links(html, base_url=page_url, href_pattern=_TEXT_LINK)
            if not links:
                reached_since = True
                break

            page_all_old = True
            added_on_page = 0
            for url, link_title in links:
                if len(articles) >= max_articles:
                    next_cursor = str(page)
                    break

                published = _published_from_url(url)
                if published and published >= since:
                    page_all_old = False

                if published and published < since:
                    continue

                external_id = extract_id_from_url(url)
                if not external_id or external_id in seen_ids:
                    continue
                seen_ids.add(external_id)

                # Быстрый путь: title+дата из листинга — без тяжёлого enrich.
                if link_title and published:
                    article = RawNewsArticle(
                        outlet=self.key,
                        external_id=external_id,
                        url=url,
                        title=link_title.strip(),
                        published_at=published,
                    )
                else:
                    article = await enrich_url(
                        client,
                        url,
                        outlet=self.key,
                        external_id=external_id,
                        fallback_title=link_title,
                        fallback_published=published,
                    )
                    if article is None:
                        continue

                pub = ensure_aware(article.published_at)
                if pub and pub < since:
                    continue
                if pub and pub >= since:
                    page_all_old = False
                articles.append(article)
                added_on_page += 1
            else:
                if page_all_old:
                    reached_since = True
                    break
                if added_on_page == 0:
                    # Та же страница / дубликаты — не крутимся бесконечно.
                    logger.warning(
                        "msk1 page=%s: 0 новых статей, стоп (url=%s)",
                        page,
                        page_url,
                    )
                    reached_since = True
                    break
                page += 1
                continue
            break

        articles.sort(key=lambda a: a.published_at, reverse=True)
        if next_cursor is None and not reached_since and pages_done >= max_pages:
            next_cursor = str(page + 1) if articles else str(page)
        elif next_cursor is None and not reached_since:
            next_cursor = str(page + 1) if articles else None
        return CollectResult(
            articles=articles,
            next_cursor=next_cursor if not reached_since else None,
            reached_since=reached_since,
        )


def _listing_page_url(cfg_url: str | None, page: int) -> str:
    """Поддержка и `...?page={page}`, и голого `https://msk1.ru/text/`."""
    template = (cfg_url or _LISTING_URL).strip()
    if "{page}" in template:
        return template.format(page=page)
    base = template.rstrip("/")
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}page={page}"


async def _fetch_listing(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[int, str] | None:
    try:
        response = await client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.status_code, response.text
    except httpx.HTTPError as exc:
        logger.warning("msk1 listing %s: %s", url, exc)
        return None


def _published_from_url(url: str) -> datetime | None:
    m = _URL_DATE.search(url)
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return datetime(year, month, day, tzinfo=UTC)

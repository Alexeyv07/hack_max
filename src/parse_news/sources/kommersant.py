"""Адаптер Коммерсант (HTML listing + archive)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx

from parse_news.http import fetch_text
from parse_news.models.article import RawNewsArticle
from parse_news.sources.base import BaseNewsSource, CollectMode, CollectResult
from parse_news.sources.common import (
    enrich_from_html,
    ensure_aware,
    extract_id_from_url,
    fetch_optional,
    find_links,
    iter_days_backward,
)
from project.config import NewsSourceConfig
from project.logging_setup import get_logger

logger = get_logger(__name__)

_DEFAULT_LISTING = "https://www.kommersant.ru/rubric/6"
_ARCHIVE_URL = "https://www.kommersant.ru/archive/?date={date}"
_DOC_LINK = re.compile(r"/doc/\d+")
_RUBRIC_MARKER = "/rubric/6"


class KommersantSource(BaseNewsSource):
    key = "kommersant"

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
    ) -> CollectResult:
        if mode == "incremental":
            return await self._collect_incremental(client, since=since, max_articles=max_articles)
        return await self._collect_backfill(
            client,
            since=since,
            listing_cursor=listing_cursor,
            max_articles=max_articles,
        )

    async def _collect_incremental(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        max_articles: int,
    ) -> CollectResult:
        listing_url = self.cfg.listing_url or _DEFAULT_LISTING
        try:
            html = await fetch_text(client, listing_url)
        except httpx.HTTPError as exc:
            logger.error("Коммерсант listing недоступен %s: %s", listing_url, exc)
            raise

        doc_urls = _unique_doc_urls(html, base_url=listing_url)
        articles: list[RawNewsArticle] = []
        for url in doc_urls:
            if len(articles) >= max_articles:
                break
            article = await self._fetch_doc(client, url, since=since)
            if article is not None:
                articles.append(article)

        articles.sort(key=lambda a: a.published_at, reverse=True)
        return CollectResult(articles=articles, next_cursor=None, reached_since=False)

    async def _collect_backfill(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        listing_cursor: str | None,
        max_articles: int,
    ) -> CollectResult:
        today = datetime.now(UTC).date()
        since_date = since.date()
        if listing_cursor:
            try:
                day = datetime.strptime(listing_cursor, "%Y-%m-%d").date()
            except ValueError:
                day = today
        else:
            day = today

        articles: list[RawNewsArticle] = []
        reached_since = False
        next_cursor: str | None = None

        for current_day in iter_days_backward(day, since_date):
            if len(articles) >= max_articles:
                next_cursor = current_day.isoformat()
                break

            archive_url = (self.cfg.archive_url or _ARCHIVE_URL).format(
                date=current_day.isoformat()
            )
            status, html = await fetch_optional(client, archive_url)
            if status != 200 or not html:
                logger.warning("Коммерсант архив %s: HTTP %s", archive_url, status)
                if current_day <= since_date:
                    reached_since = True
                continue

            doc_urls = _unique_doc_urls(html, base_url=archive_url)
            for url in doc_urls:
                if len(articles) >= max_articles:
                    next_cursor = current_day.isoformat()
                    break
                article = await self._fetch_doc(client, url, since=since)
                if article is not None:
                    articles.append(article)
            else:
                if current_day <= since_date:
                    reached_since = True
                continue
            break

        articles.sort(key=lambda a: a.published_at, reverse=True)
        if next_cursor is None and day <= since_date:
            reached_since = True
        return CollectResult(
            articles=articles,
            next_cursor=next_cursor,
            reached_since=reached_since,
        )

    async def _fetch_doc(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        since: datetime,
    ) -> RawNewsArticle | None:
        external_id = extract_id_from_url(url)
        if not external_id:
            return None

        status, html = await fetch_optional(client, url)
        if status != 200 or not html:
            return None
        if _RUBRIC_MARKER not in html:
            return None

        article = enrich_from_html(
            html,
            outlet=self.key,
            url=url,
            external_id=external_id,
        )
        published = ensure_aware(article.published_at)
        if published and published < since:
            return None
        return article


def _unique_doc_urls(html: str, *, base_url: str) -> list[str]:
    links = find_links(html, base_url=base_url, href_pattern=_DOC_LINK)
    seen: set[str] = set()
    out: list[str] = []
    for url, _ in links:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out

"""Адаптер РИА Новости (RSS + дневной архив)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx

from parse_news.http import fetch_text
from parse_news.models.article import RawNewsArticle
from parse_news.sources.base import BaseNewsSource, CollectMode, CollectResult
from parse_news.sources.common import (
    collect_from_rss,
    enrich_url,
    ensure_aware,
    extract_id_from_url,
    find_links,
    iter_days_backward,
)
from project.config import NewsSourceConfig
from project.logging_setup import get_logger

logger = get_logger(__name__)

_DEFAULT_FEED = "https://ria.ru/export/rss2/index.xml"
_DAY_PAGE = "https://ria.ru/{day}/"
_RIA_LINK = re.compile(r"(?:ria\.ru|riaru\.online)/\d{8}/", re.I)


class RiaSource(BaseNewsSource):
    key = "ria"

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
        )

    async def _collect_incremental(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        max_articles: int,
        max_pages: int = 5,
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
            logger.error("РИА RSS недоступен %s: %s", feed_url, exc)
            raise
        return CollectResult(articles=articles, next_cursor=None, reached_since=False)

    async def _collect_backfill(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        listing_cursor: str | None,
        max_articles: int,
        max_pages: int = 5,
    ) -> CollectResult:
        today = datetime.now(UTC).date()
        since_date = since.date()
        if listing_cursor:
            try:
                day = datetime.strptime(listing_cursor, "%Y%m%d").date()
            except ValueError:
                day = today
        else:
            day = today

        articles: list[RawNewsArticle] = []
        reached_since = False
        next_cursor: str | None = None

        for current_day in iter_days_backward(day, since_date):
            if len(articles) >= max_articles:
                next_cursor = current_day.strftime("%Y%m%d")
                break

            day_str = current_day.strftime("%Y%m%d")
            page_url = _DAY_PAGE.format(day=day_str)
            try:
                html = await fetch_text(client, page_url)
            except httpx.HTTPError as exc:
                logger.warning("РИА архив %s: %s", page_url, exc)
                if current_day < since_date:
                    reached_since = True
                continue

            links = find_links(html, base_url=page_url, href_pattern=_RIA_LINK)
            for url, link_title in links:
                if len(articles) >= max_articles:
                    next_cursor = day_str
                    break

                external_id = extract_id_from_url(url)
                if not external_id:
                    external_id = url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
                if not external_id:
                    continue

                fallback_pub = datetime(
                    current_day.year,
                    current_day.month,
                    current_day.day,
                    tzinfo=UTC,
                )
                try:
                    article = await enrich_url(
                        client,
                        url,
                        outlet=self.key,
                        external_id=external_id,
                        fallback_title=link_title,
                        fallback_published=fallback_pub,
                    )
                except httpx.HTTPError as exc:
                    logger.debug("РИА статья %s: %s", url, exc)
                    continue

                if article is None:
                    if link_title:
                        article = RawNewsArticle(
                            outlet=self.key,
                            external_id=external_id,
                            url=url,
                            title=link_title,
                            published_at=fallback_pub,
                        )
                    else:
                        continue

                published = ensure_aware(article.published_at) or fallback_pub
                if published < since:
                    reached_since = True
                    continue
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

"""Адаптер m24.ru (RSS + numeric ID walk)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx

from parse_news.models.article import RawNewsArticle
from parse_news.sources.base import BaseNewsSource, CollectMode, CollectResult
from parse_news.sources.common import (
    article_from_rss,
    enrich_from_html,
    ensure_aware,
    extract_id_from_url,
    fetch_optional,
    iter_days_backward,
)
from parser_common.http import fetch_text
from parser_common.rss import parse_rss
from project.config import NewsSourceConfig
from project.logging_setup import get_logger

logger = get_logger(__name__)

_DEFAULT_FEED = "https://www.m24.ru/rss.xml"
_NEWS_URL = "https://www.m24.ru/news/{ddmmyyyy}/{news_id}"
_MAX_DATE_TRIES = 7


class M24Source(BaseNewsSource):
    key = "m24"

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
            xml_text = await fetch_text(client, feed_url)
        except httpx.HTTPError as exc:
            logger.error("m24 RSS недоступен %s: %s", feed_url, exc)
            raise

        articles: list[RawNewsArticle] = []
        for item in parse_rss(xml_text):
            if len(articles) >= max_articles:
                break
            article = article_from_rss(item, outlet=self.key)
            if article is None:
                continue
            published = ensure_aware(article.published_at)
            if published and published < since:
                continue
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
        max_pages: int = 5,
    ) -> CollectResult:
        max_id, date_prefix_cache = await self._resolve_start_id(client, listing_cursor)
        if max_id <= 0:
            return CollectResult(articles=[], next_cursor=None, reached_since=True)

        current_id = max_id
        articles: list[RawNewsArticle] = []
        reached_since = False
        consecutive_miss = 0
        last_processed = current_id

        today = datetime.now(UTC).date()
        since_date = since.date()
        day_list = iter_days_backward(today, since_date)

        while len(articles) < max_articles and consecutive_miss < 50:
            article, used_prefix = await self._probe_article(
                client,
                news_id=current_id,
                day_list=day_list,
                cached_prefix=date_prefix_cache,
            )
            last_processed = current_id

            if article is None:
                consecutive_miss += 1
            else:
                consecutive_miss = 0
                if used_prefix:
                    date_prefix_cache = used_prefix
                published = ensure_aware(article.published_at)
                if published and published < since:
                    reached_since = True
                    break
                articles.append(article)

            current_id -= 1

        articles.sort(key=lambda a: a.published_at, reverse=True)
        next_cursor: str | None = None
        if not reached_since and (len(articles) >= max_articles or consecutive_miss < 50):
            next_cursor = str(last_processed - 1)

        return CollectResult(
            articles=articles,
            next_cursor=next_cursor,
            reached_since=reached_since or consecutive_miss >= 50,
        )

    async def _resolve_start_id(
        self,
        client: httpx.AsyncClient,
        listing_cursor: str | None,
    ) -> tuple[int, str | None]:
        if listing_cursor and listing_cursor.isdigit():
            return int(listing_cursor), None

        feed_url = self.cfg.feed_url or _DEFAULT_FEED
        try:
            xml_text = await fetch_text(client, feed_url)
        except httpx.HTTPError:
            return 0, None

        max_id = 0
        prefix: str | None = None
        for item in parse_rss(xml_text):
            ext = extract_id_from_url(item.link)
            if ext and ext.isdigit():
                nid = int(ext)
                if nid > max_id:
                    max_id = nid
                    m = re.search(r"/news/(\d{8})/", item.link)
                    if m:
                        prefix = m.group(1)
        return max_id, prefix

    async def _probe_article(
        self,
        client: httpx.AsyncClient,
        *,
        news_id: int,
        day_list: list,
        cached_prefix: str | None,
    ) -> tuple[RawNewsArticle | None, str | None]:
        prefixes: list[str] = []
        if cached_prefix:
            prefixes.append(cached_prefix)
        for day in day_list[:_MAX_DATE_TRIES]:
            ddmmyyyy = day.strftime("%d%m%Y")
            if ddmmyyyy not in prefixes:
                prefixes.append(ddmmyyyy)

        for prefix in prefixes:
            url = _NEWS_URL.format(ddmmyyyy=prefix, news_id=news_id)
            status, html = await fetch_optional(client, url)
            if status != 200 or not html:
                continue

            external_id = str(news_id)
            article = enrich_from_html(
                html,
                outlet=self.key,
                url=url,
                external_id=external_id,
            )
            return article, prefix

        return None, None

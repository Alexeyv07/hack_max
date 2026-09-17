"""Адаптер ТАСС (RSS + sitemap / Google News backfill)."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import quote_plus

import httpx

from parse_news.http import fetch_text
from parse_news.models.article import RawNewsArticle
from parse_news.rss import parse_rss
from parse_news.sources.base import BaseNewsSource, CollectMode, CollectResult
from parse_news.sources.common import (
    collect_from_rss,
    ensure_aware,
    extract_id_from_url,
    fetch_optional,
    parse_sitemap_entries,
    title_from_slug,
)
from project.config import NewsSourceConfig
from project.logging_setup import get_logger

logger = get_logger(__name__)

_DEFAULT_FEED = "https://tass.ru/rss/v2.xml"
_SITEMAP_URL = "https://tass.ru/sitemap/sitemap_news{idx}.xml"
_GOOGLE_NEWS = "https://news.google.com/rss/search?q={query}&hl=ru&gl=RU&ceid=RU:ru"
_TASS_ID_RE = re.compile(r"/(\d{5,})/?$")


class TassSource(BaseNewsSource):
    key = "tass"

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
            logger.error("ТАСС RSS недоступен %s: %s", feed_url, exc)
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
        if listing_cursor and listing_cursor.startswith("gnews:"):
            return await self._backfill_google_news(
                client,
                since=since,
                listing_cursor=listing_cursor,
                max_articles=max_articles,
            )

        sitemap_result = await self._backfill_sitemaps(
            client,
            since=since,
            listing_cursor=listing_cursor,
            max_articles=max_articles,
        )
        if sitemap_result.articles or (
            sitemap_result.next_cursor and not sitemap_result.next_cursor.startswith("gnews:")
        ):
            return sitemap_result

        logger.warning("ТАСС sitemap недоступен — fallback на Google News RSS")
        return await self._backfill_google_news(
            client,
            since=since,
            listing_cursor="gnews:0",
            max_articles=max_articles,
        )

    async def _backfill_sitemaps(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        listing_cursor: str | None,
        max_articles: int,
        max_pages: int = 5,
    ) -> CollectResult:
        sitemap_idx, offset = _parse_cursor(listing_cursor)
        articles: list[RawNewsArticle] = []
        reached_since = False
        next_cursor: str | None = None
        empty_sitemaps = 0

        while len(articles) < max_articles and empty_sitemaps < 3:
            url = _SITEMAP_URL.format(idx=sitemap_idx)
            status, xml_text = await fetch_optional(client, url)
            if status in {403, 401}:
                logger.warning(
                    "ТАСС sitemap недоступен (HTTP %s) — сразу fallback на Google News",
                    status,
                )
                return CollectResult(articles=[], next_cursor="gnews:0", reached_since=False)
            if status == 0 or not xml_text:
                logger.warning("ТАСС sitemap %s HTTP %s", url, status)
                empty_sitemaps += 1
                sitemap_idx += 1
                offset = 0
                continue
            if status == 404:
                reached_since = True
                break

            empty_sitemaps = 0
            try:
                entries = parse_sitemap_entries(xml_text)
            except Exception as exc:
                logger.warning("Не удалось разобрать sitemap ТАСС %s: %s", url, exc)
                sitemap_idx += 1
                offset = 0
                continue

            if not entries:
                sitemap_idx += 1
                offset = 0
                continue

            newest = max((lm for _, lm in entries if lm), default=None)
            if newest and newest < since:
                reached_since = True
                break

            batch = entries[offset:]
            if not batch:
                sitemap_idx += 1
                offset = 0
                continue

            for loc, lastmod in batch:
                if len(articles) >= max_articles:
                    next_cursor = f"{sitemap_idx}:{offset}"
                    break

                published = ensure_aware(lastmod) or datetime.now(UTC)
                if published < since:
                    reached_since = True
                    continue

                external_id = _tass_external_id(loc)
                if not external_id:
                    offset += 1
                    continue

                articles.append(
                    RawNewsArticle(
                        outlet=self.key,
                        external_id=external_id,
                        url=loc,
                        title=title_from_slug(loc) or external_id,
                        published_at=published,
                        body=None,
                    )
                )
                offset += 1
            else:
                sitemap_idx += 1
                offset = 0
                continue
            break

        articles.sort(key=lambda a: a.published_at, reverse=True)
        if not articles and empty_sitemaps:
            return CollectResult(articles=[], next_cursor="gnews:0", reached_since=False)
        if next_cursor is None and not reached_since and len(articles) >= max_articles:
            next_cursor = f"{sitemap_idx}:{offset}"
        return CollectResult(
            articles=articles,
            next_cursor=next_cursor,
            reached_since=reached_since,
        )

    async def _backfill_google_news(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        listing_cursor: str | None,
        max_articles: int,
        max_pages: int = 5,
    ) -> CollectResult:
        days = max(1, (datetime.now(UTC) - since).days)
        query = quote_plus(f"site:tass.ru when:{days}d")
        url = _GOOGLE_NEWS.format(query=query)
        try:
            xml_text = await fetch_text(client, url)
        except httpx.HTTPError as exc:
            logger.error("Google News для ТАСС недоступен: %s", exc)
            raise

        offset = 0
        if listing_cursor and listing_cursor.startswith("gnews:"):
            try:
                offset = int(listing_cursor.split(":", 1)[1])
            except ValueError:
                offset = 0

        items = parse_rss(xml_text)[offset:]
        articles: list[RawNewsArticle] = []
        reached_since = False
        idx = offset

        for item in items:
            if len(articles) >= max_articles:
                break
            idx += 1
            # Google News отдаёт redirect-ссылки; в description часто только «tass.ru».
            # Для backfill принимаем item целиком: title/body/date из RSS, id из guid.
            blob = f"{item.link}\n{item.guid or ''}\n{item.description or ''}\n{item.title}"
            if "tass.ru" not in blob.lower() and "тасс" not in (item.title or "").lower():
                # Запрос уже site:tass.ru — всё равно принимаем.
                pass

            external_id = extract_id_from_url(item.link or "") or _stable_gnews_id(
                item.guid or item.link
            )
            if not item.title or not external_id:
                continue

            published = ensure_aware(item.published_at) or datetime.now(UTC)
            if published < since:
                reached_since = True
                continue

            articles.append(
                RawNewsArticle(
                    outlet=self.key,
                    external_id=external_id[:96],
                    url=item.link,
                    title=item.title.strip(),
                    published_at=published,
                    body=item.description,
                    image_url=item.image_url,
                )
            )

        next_cursor: str | None = None
        if len(articles) >= max_articles and idx < offset + len(items) and not reached_since:
            next_cursor = f"gnews:{idx}"
        elif not articles and items:
            # Нечего разобрать — не помечаем complete, чтобы можно было повторить.
            next_cursor = f"gnews:{offset}"
            reached_since = False
        else:
            reached_since = True

        articles.sort(key=lambda a: a.published_at, reverse=True)
        return CollectResult(
            articles=articles,
            next_cursor=next_cursor,
            reached_since=reached_since,
        )


def _parse_cursor(cursor: str | None) -> tuple[int, int]:
    if not cursor or cursor.startswith("gnews:"):
        return 0, 0
    parts = cursor.split(":", 1)
    try:
        idx = int(parts[0])
        off = int(parts[1]) if len(parts) > 1 else 0
        return idx, off
    except ValueError:
        return 0, 0


def _tass_external_id(url: str) -> str | None:
    ext = extract_id_from_url(url)
    if ext:
        return ext
    m = _TASS_ID_RE.search(url.rstrip("/"))
    return m.group(1) if m else None


def _stable_gnews_id(raw: str) -> str:
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"gnews-{digest}"

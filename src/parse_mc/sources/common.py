"""Общие хелперы адаптеров УК → RawMcNotice (обёртка над parser_common)."""

from __future__ import annotations

from datetime import datetime

import httpx

from parse_mc.models.notice import RawMcNotice
from parser_common.geo_text import extract_street_lines
from parser_common.scrape import (
    ScrapedPage,
    collect_pages_from_rss,
    enrich_page_from_html,
    ensure_aware,
    extract_id_from_url,
    fetch_optional,
    find_links,
    parse_datetime,
    parse_ru_date,
    stable_id,
)
from parser_common.scrape import (
    enrich_url as scrape_enrich_url,
)

__all__ = [
    "collect_from_rss",
    "dedupe_notices",
    "enrich_notice_from_html",
    "enrich_url",
    "ensure_aware",
    "extract_id_from_url",
    "extract_street_lines",
    "fetch_optional",
    "find_links",
    "parse_datetime",
    "parse_ru_date",
    "stable_id",
]


def _to_notice(
    page: ScrapedPage,
    *,
    outlet: str,
    streets: tuple[str, ...] = (),
) -> RawMcNotice:
    merged = streets or extract_street_lines(f"{page.title}\n{page.body or ''}")
    return RawMcNotice(
        outlet=outlet,
        external_id=page.external_id,
        url=page.url,
        title=page.title,
        published_at=page.published_at,
        body=page.body,
        image_url=page.image_url,
        streets=merged,
        geo_city="Москва",
    )


def enrich_notice_from_html(
    html: str,
    *,
    outlet: str,
    url: str,
    external_id: str,
    fallback_title: str | None = None,
    fallback_body: str | None = None,
    fallback_published: datetime | None = None,
    streets: tuple[str, ...] = (),
) -> RawMcNotice:
    page = enrich_page_from_html(
        html,
        url=url,
        external_id=external_id,
        fallback_title=fallback_title,
        fallback_body=fallback_body,
        fallback_published=fallback_published,
    )
    return _to_notice(page, outlet=outlet, streets=streets)


async def enrich_url(
    client: httpx.AsyncClient,
    url: str,
    *,
    outlet: str,
    external_id: str,
    fallback_title: str | None = None,
    fallback_published: datetime | None = None,
    streets: tuple[str, ...] = (),
) -> RawMcNotice | None:
    page = await scrape_enrich_url(
        client,
        url,
        external_id=external_id,
        fallback_title=fallback_title,
        fallback_published=fallback_published,
    )
    if page is None:
        return None
    return _to_notice(page, outlet=outlet, streets=streets)


def dedupe_notices(notices: list[RawMcNotice]) -> list[RawMcNotice]:
    seen: set[str] = set()
    out: list[RawMcNotice] = []
    for notice in notices:
        if notice.external_id in seen:
            continue
        seen.add(notice.external_id)
        out.append(notice)
    return out


async def collect_from_rss(
    client: httpx.AsyncClient,
    feed_url: str,
    *,
    outlet: str,
    since: datetime,
    max_articles: int,
) -> list[RawMcNotice]:
    pages = await collect_pages_from_rss(client, feed_url, since=since, max_articles=max_articles)
    return [_to_notice(page, outlet=outlet) for page in pages]

"""Разбор RSS 2.0 (xml.etree.ElementTree)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from parse_news.html_util import strip_html


@dataclass(frozen=True, slots=True)
class RssItem:
    title: str
    link: str
    guid: str | None
    published_at: datetime | None
    description: str | None
    image_url: str | None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    raw = element.text or ""
    if not raw and len(element):
        raw = ET.tostring(element, encoding="unicode", method="text")
    value = raw.strip()
    return value or None


def _find_child(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _local_name(child.tag) == name:
            return child
    return None


def _find_enclosure_url(item: ET.Element) -> str | None:
    for child in item:
        if _local_name(child.tag) != "enclosure":
            continue
        url = child.attrib.get("url")
        if url:
            return url.strip()
    return None


def _find_media_content_url(item: ET.Element) -> str | None:
    for child in item:
        local = _local_name(child.tag)
        if local not in {"content", "thumbnail"}:
            continue
        url = child.attrib.get("url")
        if url:
            return url.strip()
    return None


def _parse_pub_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw.strip())
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    except (TypeError, ValueError, IndexError):
        return None


def parse_rss(xml_text: str) -> list[RssItem]:
    root = ET.fromstring(xml_text)
    if _local_name(root.tag) == "rss":
        channel = _find_child(root, "channel")
        if channel is None:
            channel = root
    elif _local_name(root.tag) == "channel":
        channel = root
    else:
        channel = _find_child(root, "channel")
        if channel is None:
            channel = root

    items: list[RssItem] = []
    for child in channel:
        if _local_name(child.tag) != "item":
            continue

        title = _text(_find_child(child, "title")) or ""
        link = _text(_find_child(child, "link")) or ""
        if not link:
            continue

        guid = _text(_find_child(child, "guid"))
        description_raw = _text(_find_child(child, "description"))
        description = strip_html(description_raw) if description_raw else None
        published_at = _parse_pub_date(_text(_find_child(child, "pubDate")))
        image_url = _find_enclosure_url(child) or _find_media_content_url(child)

        items.append(
            RssItem(
                title=title.strip(),
                link=link.strip(),
                guid=guid.strip() if guid else None,
                published_at=published_at,
                description=description,
                image_url=image_url,
            )
        )
    return items

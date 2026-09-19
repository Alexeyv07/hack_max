"""Live smoke по news outlets. По умолчанию skip — нужна сеть.

set RUN_LIVE_NEWS=1
set PYTHONPATH=src
pytest tests/parse_news/test_live_smoke.py -q
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

from parse_news.http import make_client
from parse_news.registry import get_sources
from project.config import get_settings

pytestmark = pytest.mark.network


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_NEWS", "").strip() not in {"1", "true", "yes"},
    reason="set RUN_LIVE_NEWS=1 to hit live news outlets",
)
def test_live_incremental_collect_one_page() -> None:
    settings = get_settings()
    cfg = settings.news_parser
    sources = get_sources(cfg)
    assert sources, "нет enabled источников в конфиге"

    since = datetime.now(UTC) - timedelta(days=max(1, cfg.lookback_days))
    timeout = float(cfg.collect_timeout_seconds)

    async def _run() -> dict[str, int]:
        counts: dict[str, int] = {}
        async with make_client(settings) as client:
            for source in sources:
                result = await asyncio.wait_for(
                    source.collect(
                        client,
                        since=since,
                        mode="incremental",
                        listing_cursor=None,
                        max_articles=3,
                        max_pages=1,
                    ),
                    timeout=timeout,
                )
                counts[source.key] = len(result.articles)
        return counts

    counts = asyncio.run(_run())
    empty = [k for k, n in counts.items() if n == 0]
    assert not empty, f"outlets without articles: {empty}; counts={counts}"

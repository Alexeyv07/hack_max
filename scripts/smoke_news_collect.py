"""Live smoke: один incremental collect (1 страница) по каждому enabled outlet.

Без записи в БД — только проверка, что адаптеры живы и отдают статьи.

Запуск из корня репо::

  set PYTHONPATH=src
  python scripts/smoke_news_collect.py
  python scripts/smoke_news_collect.py --outlet m24
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parse_news.http import make_client  # noqa: E402
from parse_news.registry import get_sources  # noqa: E402
from project.config import get_settings  # noqa: E402
from project.logging_setup import get_logger, setup_logging  # noqa: E402

logger = get_logger(__name__)


async def _smoke_one(
    *,
    outlet: str | None,
    max_articles: int,
    max_pages: int,
) -> int:
    settings = get_settings()
    cfg = settings.news_parser
    sources = get_sources(cfg)
    if outlet:
        sources = [s for s in sources if s.key == outlet]
        if not sources:
            logger.error("Outlet %r не найден или disabled", outlet)
            return 1

    since = datetime.now(UTC) - timedelta(days=max(1, cfg.lookback_days))
    timeout = float(cfg.collect_timeout_seconds)
    failed = 0

    async with make_client(settings) as client:
        for source in sources:
            try:
                result = await asyncio.wait_for(
                    source.collect(
                        client,
                        since=since,
                        mode="incremental",
                        listing_cursor=None,
                        max_articles=max_articles,
                        max_pages=max_pages,
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                logger.error("%s: TIMEOUT after %ss", source.key, timeout)
                failed += 1
                continue
            except Exception as exc:
                logger.exception("%s: FAIL %s", source.key, exc)
                failed += 1
                continue

            n = len(result.articles)
            if n == 0:
                logger.error("%s: 0 articles", source.key)
                failed += 1
                continue

            sample = result.articles[0]
            logger.info(
                "%s: OK articles=%d sample_id=%s title=%s",
                source.key,
                n,
                sample.source_msg_id,
                (sample.title or "")[:80],
            )

    if failed:
        logger.error("Smoke failed: %d outlet(s)", failed)
        return 1
    logger.info("Smoke OK: %d outlet(s)", len(sources))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Live smoke collect for news outlets")
    parser.add_argument("--outlet", help="Только один outlet (например m24)")
    parser.add_argument("--max-articles", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=1)
    args = parser.parse_args()

    setup_logging()
    raise SystemExit(
        asyncio.run(
            _smoke_one(
                outlet=args.outlet,
                max_articles=max(1, args.max_articles),
                max_pages=max(1, args.max_pages),
            )
        )
    )


if __name__ == "__main__":
    main()

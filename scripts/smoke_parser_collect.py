"""Live smoke: collect без записи в БД для news и/или mc парсеров.

Запуск из корня репо::

  set PYTHONPATH=src
  python scripts/smoke_parser_collect.py
  python scripts/smoke_parser_collect.py --parser news
  python scripts/smoke_parser_collect.py --parser mc --outlet moek
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from project.config import get_settings  # noqa: E402
from project.logging_setup import get_logger, setup_logging  # noqa: E402

logger = get_logger(__name__)

ParserKind = Literal["news", "mc"]


def _result_items(result: Any) -> list[Any]:
    if hasattr(result, "articles"):
        return list(result.articles)
    if hasattr(result, "notices"):
        return list(result.notices)
    return []


async def _smoke_parser(
    kind: ParserKind,
    *,
    outlet: str | None,
    max_articles: int,
    max_pages: int,
) -> int:
    settings = get_settings()
    if kind == "news":
        from parse_news.http import make_client
        from parse_news.registry import get_sources

        cfg = settings.news_parser
    else:
        from parse_mc.http import make_client
        from parse_mc.registry import get_sources

        cfg = settings.mc_parser

    sources = get_sources(cfg)
    if outlet:
        sources = [s for s in sources if s.key == outlet]
        if not sources:
            logger.error("[%s] outlet %r не найден или disabled", kind, outlet)
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
                logger.error("[%s] %s: TIMEOUT after %ss", kind, source.key, timeout)
                failed += 1
                continue
            except Exception as exc:
                logger.exception("[%s] %s: FAIL %s", kind, source.key, exc)
                failed += 1
                continue

            items = _result_items(result)
            if not items:
                logger.error("[%s] %s: 0 items", kind, source.key)
                failed += 1
                continue

            sample = items[0]
            logger.info(
                "[%s] %s: OK items=%d sample_id=%s title=%s",
                kind,
                source.key,
                len(items),
                getattr(sample, "source_msg_id", "?"),
                (getattr(sample, "title", "") or "")[:80],
            )

    if failed:
        logger.error("[%s] Smoke failed: %d outlet(s)", kind, failed)
        return 1
    logger.info("[%s] Smoke OK: %d outlet(s)", kind, len(sources))
    return 0


async def _run(
    *,
    parsers: list[ParserKind],
    outlet: str | None,
    max_articles: int,
    max_pages: int,
) -> int:
    rc = 0
    for kind in parsers:
        if outlet and len(parsers) > 1:
            # outlet имеет смысл только для одного парсера
            logger.error("--outlet нельзя с --parser all; укажите --parser news|mc")
            return 1
        part = await _smoke_parser(
            kind,
            outlet=outlet,
            max_articles=max_articles,
            max_pages=max_pages,
        )
        rc = rc or part
    return rc


def main() -> None:
    parser = argparse.ArgumentParser(description="Live smoke collect for parsers")
    parser.add_argument(
        "--parser",
        choices=("news", "mc", "all"),
        default="all",
        help="Какой воркер проверить (default: all)",
    )
    parser.add_argument("--outlet", help="Только один outlet (например m24 / moek)")
    parser.add_argument("--max-articles", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=1)
    args = parser.parse_args()

    parsers: list[ParserKind] = ["news", "mc"] if args.parser == "all" else [args.parser]

    setup_logging()
    raise SystemExit(
        asyncio.run(
            _run(
                parsers=parsers,
                outlet=args.outlet,
                max_articles=max(1, args.max_articles),
                max_pages=max(1, args.max_pages),
            )
        )
    )


if __name__ == "__main__":
    main()

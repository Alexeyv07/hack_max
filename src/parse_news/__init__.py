"""KAN-11: парсер новостей СМИ → ParserCandidate → events."""

from __future__ import annotations

from parse_news.handlers.worker import run_news_parser

__all__ = ["run_news_parser"]

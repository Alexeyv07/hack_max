"""Бизнес-логика парсера новостей."""

from parse_news.handlers.ingest import article_to_candidate, persist_article
from parse_news.handlers.worker import run_news_parser

__all__ = ["article_to_candidate", "persist_article", "run_news_parser"]

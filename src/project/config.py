"""Конфигурация приложения: YAML + переопределение через переменные окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Корень репозитория (родитель каталога src/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONF_DIR = PROJECT_ROOT / "conf"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError(f"Не удалось разобрать булево значение из {value!r}")


def _coerce(raw: str, sample: Any) -> Any:
    """Привести строку из env к типу, подсказанному значением из YAML."""
    if sample is None:
        return raw
    if isinstance(sample, bool):
        return _parse_bool(raw)
    if isinstance(sample, int) and not isinstance(sample, bool):
        return int(raw)
    if isinstance(sample, float):
        return float(raw)
    return raw


def _deep_set(data: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    cursor: dict[str, Any] = data
    for part in parts[:-1]:
        nested = cursor.get(part)
        if not isinstance(nested, dict):
            nested = {}
            cursor[part] = nested
        cursor = nested
    cursor[parts[-1]] = value


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """
    Переменные окружения перекрывают YAML:
      - вложенный вид: DATABASE__HOST, LOGGING__LEVEL (двойное подчёркивание)
      - короткие алиасы: MAX_BOT_TOKEN, DATABASE_PASSWORD, LOG_LEVEL, ...
    """
    alias_map: dict[str, str] = {
        "DATABASE_HOST": "database.host",
        "DATABASE_PORT": "database.port",
        "DATABASE_NAME": "database.name",
        "DATABASE_USER": "database.user",
        "DATABASE_PASSWORD": "database.password",
        "MAX_BOT_TOKEN": "max.bot_token",
        "MAX_API_BASE_URL": "max.api_base_url",
        "APP_DEBUG": "app.debug",
        "LOG_LEVEL": "logging.level",
        "LOG_FORMAT": "logging.format",
        "API_HOST": "api.host",
        "API_PORT": "api.port",
        "ENABLE_BOT": "runtime.enable_bot",
        "ENABLE_API": "runtime.enable_api",
        "ENABLE_NEWS_PARSER": "runtime.enable_news_parser",
        "ENABLE_MC_PARSER": "runtime.enable_mc_parser",
        "ENABLE_CHAT_PARSER": "runtime.enable_chat_parser",
        "EVENTS_NEARBY_RADIUS_M": "events.nearby_radius_m",
        "EVENTS_CITY_RADIUS_M": "events.city_radius_m",
        "ML_DEDUP_ENABLED": "ml_dedup.enabled",
        "ML_DEDUP_ACTIVE_DAYS": "ml_dedup.active_days",
        "NOTIFY_ENABLED": "notify.enabled",
        "SUMMARIZER_PROVIDER": "notify.summarizer_provider",
        "DOCS_URL": "docs.url",
        "DOCS_GITHUB_URL": "docs.github_url",
    }

    for env_key, dotted in alias_map.items():
        if env_key not in os.environ:
            continue
        parts = dotted.split(".")
        sample: Any = data
        for part in parts:
            sample = sample.get(part) if isinstance(sample, dict) else None
        _deep_set(data, dotted, _coerce(os.environ[env_key], sample))

    prefix_skip = set(alias_map)
    for env_key, raw in os.environ.items():
        if env_key in prefix_skip or "__" not in env_key:
            continue
        # DATABASE__HOST -> database.host
        dotted = env_key.lower().replace("__", ".")
        parts = dotted.split(".")
        sample: Any = data
        for part in parts:
            sample = sample.get(part) if isinstance(sample, dict) else None
        _deep_set(data, dotted, _coerce(raw, sample))

    return data


@dataclass(frozen=True, slots=True)
class AppConfig:
    name: str = "hack-max"
    debug: bool = False


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    level: str = "INFO"
    format: str = "console"


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    name: str = "hack_max"
    user: str = "hack_max"
    password: str | None = None
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10

    def sqlalchemy_url(self) -> str:
        """Собрать DSN SQLAlchemy из полей конфига."""
        password = self.password or ""
        return f"postgresql+psycopg2://{self.user}:{password}@{self.host}:{self.port}/{self.name}"


@dataclass(frozen=True, slots=True)
class MaxConfig:
    bot_token: str | None = None
    api_base_url: str = "https://botapi.max.ru"


@dataclass(frozen=True, slots=True)
class ApiConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    # Origins WebApp (localhost). CloudPub — allow_origin_regex в app.py.
    # Перекрывается api.cors_origins / API_CORS_ORIGINS.
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    )


@dataclass(frozen=True, slots=True)
class EventsConfig:
    nearby_radius_m: float = 3000.0
    city_radius_m: float = 30000.0


@dataclass(frozen=True, slots=True)
class MlDedupConfig:
    """KAN-19: дедуп / актуализация overlapping events."""

    enabled: bool = True
    # Новость «активна» для match/update столько дней (и lookback пула).
    active_days: int = 21
    duplicate_threshold: float = 0.88
    update_threshold: float = 0.72
    radius_m: float = 3000.0
    allow_hash_fallback: bool = True
    require_geo_match: bool = False
    queue_maxsize: int = 500


@dataclass(frozen=True, slots=True)
class MlEnrichConfig:
    """Time-window ML + place NER (spaCy → addresses)."""

    time_enabled: bool = True
    time_min_confidence: float = 0.45
    place_enabled: bool = True
    spacy_model: str = "ru_core_news_md"


@dataclass(frozen=True, slots=True)
class NewsSourceConfig:
    enabled: bool = True
    feed_url: str | None = None
    listing_url: str | None = None
    archive_url: str | None = None
    # Надёжность источника 0..1 для веса ленты (ЖКХ / соседские новости).
    reliability: float = 0.7


@dataclass(frozen=True, slots=True)
class NewsParserConfig:
    # bootstrap — backfill до lookback + dump snapshot; production — то же + долгий poll.
    mode: str = "bootstrap"
    lookback_days: int = 7
    poll_interval_seconds: int = 3600
    request_timeout_seconds: int = 12
    max_articles_per_source_per_run: int = 40
    max_pages_per_run: int = 5
    # Потолок статей на outlet в bootstrap (0 = без потолка, весь lookback_days).
    bootstrap_articles_per_source: int = 0
    # После bootstrap сохранить события в файл (как address seed).
    bootstrap_snapshot_path: str = "src/parser_common/data/bootstrap_events.jsonl.gz"
    collect_timeout_seconds: int = 90
    insert_batch_size: int = 25
    early_stop_known_streak: int = 15
    # Паузы, чтобы не голодать API/бот в том же event loop (нет «джиттера» — только sleep).
    source_pause_seconds: float = 0.5
    backfill_pause_seconds: float = 2.0
    user_agent: str = "HackMaxNewsBot/1.0 (+https://github.com/hack-max)"
    sources: dict[str, NewsSourceConfig] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class McSourceConfig:
    enabled: bool = True
    feed_url: str | None = None
    listing_url: str | None = None
    archive_url: str | None = None
    reliability: float = 0.75


@dataclass(frozen=True, slots=True)
class McParserConfig:
    """KAN-28: парсер сайтов управляющих компаний / ЖЭК."""

    mode: str = "bootstrap"
    lookback_days: int = 14
    poll_interval_seconds: int = 3600
    request_timeout_seconds: int = 15
    max_articles_per_source_per_run: int = 40
    max_pages_per_run: int = 5
    bootstrap_articles_per_source: int = 0
    collect_timeout_seconds: int = 120
    insert_batch_size: int = 20
    early_stop_known_streak: int = 10
    source_pause_seconds: float = 0.5
    backfill_pause_seconds: float = 2.0
    user_agent: str = "HackMaxMcBot/1.0 (+https://github.com/hack-max)"
    sources: dict[str, McSourceConfig] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NotifyConfig:
    """KAN notify: дайджесты чатов и личные приоритетные уведомления."""

    enabled: bool = False
    poll_interval_seconds: int = 30
    timezone: str = "Europe/Moscow"
    digest_hour: int = 20
    digest_jitter_minutes: int = 60
    digest_min_new_messages: int = 30
    retry_interval_seconds: int = 3600
    summarizer_provider: str = "none"
    summarizer_timeout_seconds: float = 12.0
    summarizer_retry_count: int = 1


@dataclass(frozen=True, slots=True)
class ChatParserConfig:
    """KAN-10: минимальный фильтр шума (важность — у classify ML)."""

    enabled: bool = True
    min_chars: int = 3
    flood_window_seconds: int = 90
    flood_max_repeats: int = 3
    # Max GET /updates: больше 1 — быстрее слив очереди (обработка в фоне).
    updates_limit: int = 50
    greeting_only: tuple[str, ...] = ()
    photo_attach_window_seconds: int = 600


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Какие сервисы поднимать в одном процессе main."""

    enable_bot: bool = True
    enable_api: bool = True
    enable_news_parser: bool = True
    enable_mc_parser: bool = True
    # Слушатель чатов вешается на Max Dispatcher (нужен enable_bot).
    enable_chat_parser: bool = True


@dataclass(frozen=True, slots=True)
class DocsConfig:
    """Публичные ссылки проекта (Pages + GitHub)."""

    url: str = "https://alexeyv07.github.io/hack_max/docs/"
    github_url: str = "https://github.com/Alexeyv07/hack_max"


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    app: AppConfig = field(default_factory=AppConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    max: MaxConfig = field(default_factory=MaxConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    events: EventsConfig = field(default_factory=EventsConfig)
    ml_dedup: MlDedupConfig = field(default_factory=MlDedupConfig)
    ml_enrich: MlEnrichConfig = field(default_factory=MlEnrichConfig)
    news_parser: NewsParserConfig = field(default_factory=NewsParserConfig)
    mc_parser: McParserConfig = field(default_factory=McParserConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    chat_parser: ChatParserConfig = field(default_factory=ChatParserConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    docs: DocsConfig = field(default_factory=DocsConfig)


def _parse_cors_origins(raw: Any) -> tuple[str, ...]:
    """Список CORS origins из YAML (list) или env API_CORS_ORIGINS (через запятую)."""
    env_raw = os.environ.get("API_CORS_ORIGINS")
    if env_raw is not None and env_raw.strip():
        return tuple(part.strip() for part in env_raw.split(",") if part.strip())
    if raw is None:
        return ApiConfig().cors_origins
    if isinstance(raw, str):
        return (
            tuple(part.strip() for part in raw.split(",") if part.strip())
            or ApiConfig().cors_origins
        )
    if isinstance(raw, list):
        origins = tuple(str(item).strip() for item in raw if str(item).strip())
        return origins or ApiConfig().cors_origins
    raise TypeError("api.cors_origins должен быть списком строк или строкой через запятую")


def _parse_news_sources(raw: Any) -> dict[str, NewsSourceConfig]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise TypeError("news_parser.sources должен быть словарём")
    sources: dict[str, NewsSourceConfig] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise TypeError(f"news_parser.sources.{key} должен быть словарём")
        sources[str(key)] = NewsSourceConfig(
            enabled=bool(value.get("enabled", True)),
            feed_url=value.get("feed_url"),
            listing_url=value.get("listing_url"),
            archive_url=value.get("archive_url"),
            reliability=float(value.get("reliability", 0.7)),
        )
    return sources


def _parse_mc_sources(raw: Any) -> dict[str, McSourceConfig]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise TypeError("mc_parser.sources должен быть словарём")
    sources: dict[str, McSourceConfig] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise TypeError(f"mc_parser.sources.{key} должен быть словарём")
        sources[str(key)] = McSourceConfig(
            enabled=bool(value.get("enabled", True)),
            feed_url=value.get("feed_url"),
            listing_url=value.get("listing_url"),
            archive_url=value.get("archive_url"),
            reliability=float(value.get("reliability", 0.75)),
        )
    return sources


def _parse_str_list(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    raise TypeError("ожидался список строк или строка через запятую")


def _resolve_environment() -> str:
    # Поддерживаем и распространённую опечатку APP_ENVIROMENT.
    raw = os.environ.get("APP_ENVIRONMENT") or os.environ.get("APP_ENVIROMENT") or "local"
    env = raw.strip().lower()
    if env not in {"local", "prod"}:
        raise ValueError(f"APP_ENVIRONMENT должен быть 'local' или 'prod', получено {raw!r}")
    return env


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Файл конфига не найден: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise TypeError(f"Корень конфига должен быть словарём: {path}")
    return data


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    environment = _resolve_environment()
    raw = _load_yaml(CONF_DIR / f"{environment}.yaml")
    raw = _apply_env_overrides(raw)

    app_raw = raw.get("app") or {}
    logging_raw = raw.get("logging") or {}
    database_raw = raw.get("database") or {}
    max_raw = raw.get("max") or {}
    api_raw = raw.get("api") or {}
    events_raw = raw.get("events") or {}
    ml_dedup_raw = raw.get("ml_dedup") or {}
    ml_enrich_raw = raw.get("ml_enrich") or {}
    news_parser_raw = raw.get("news_parser") or {}
    mc_parser_raw = raw.get("mc_parser") or {}
    notify_raw = raw.get("notify") or {}
    chat_parser_raw = raw.get("chat_parser") or {}
    runtime_raw = raw.get("runtime") or {}
    docs_raw = raw.get("docs") or {}

    return Settings(
        environment=environment,
        app=AppConfig(
            name=str(app_raw.get("name", "hack-max")),
            debug=bool(app_raw.get("debug", False)),
        ),
        logging=LoggingConfig(
            level=str(logging_raw.get("level", "INFO")),
            format=str(logging_raw.get("format", "console")),
        ),
        database=DatabaseConfig(
            host=str(database_raw.get("host", "localhost")),
            port=int(database_raw.get("port", 5432)),
            name=str(database_raw.get("name", "hack_max")),
            user=str(database_raw.get("user", "hack_max")),
            password=database_raw.get("password"),
            echo=bool(database_raw.get("echo", False)),
            pool_size=int(database_raw.get("pool_size", 5)),
            max_overflow=int(database_raw.get("max_overflow", 10)),
        ),
        max=MaxConfig(
            bot_token=max_raw.get("bot_token"),
            api_base_url=str(max_raw.get("api_base_url", "https://botapi.max.ru")),
        ),
        api=ApiConfig(
            host=str(api_raw.get("host", "0.0.0.0")),
            port=int(api_raw.get("port", 8000)),
            cors_origins=_parse_cors_origins(api_raw.get("cors_origins")),
        ),
        events=EventsConfig(
            nearby_radius_m=float(events_raw.get("nearby_radius_m", 3000)),
            city_radius_m=float(events_raw.get("city_radius_m", 30000)),
        ),
        ml_dedup=MlDedupConfig(
            enabled=bool(ml_dedup_raw.get("enabled", True)),
            active_days=int(ml_dedup_raw.get("active_days", 21)),
            duplicate_threshold=float(ml_dedup_raw.get("duplicate_threshold", 0.88)),
            update_threshold=float(ml_dedup_raw.get("update_threshold", 0.72)),
            radius_m=float(ml_dedup_raw.get("radius_m", 3000)),
            allow_hash_fallback=bool(ml_dedup_raw.get("allow_hash_fallback", True)),
            require_geo_match=bool(ml_dedup_raw.get("require_geo_match", False)),
            queue_maxsize=int(ml_dedup_raw.get("queue_maxsize", 500)),
        ),
        ml_enrich=MlEnrichConfig(
            time_enabled=bool(ml_enrich_raw.get("time_enabled", True)),
            time_min_confidence=float(ml_enrich_raw.get("time_min_confidence", 0.45)),
            place_enabled=bool(ml_enrich_raw.get("place_enabled", True)),
            spacy_model=str(ml_enrich_raw.get("spacy_model", "ru_core_news_md")),
        ),
        news_parser=NewsParserConfig(
            mode=str(news_parser_raw.get("mode", "bootstrap")).strip().lower(),
            lookback_days=int(news_parser_raw.get("lookback_days", 7)),
            poll_interval_seconds=int(news_parser_raw.get("poll_interval_seconds", 3600)),
            request_timeout_seconds=int(news_parser_raw.get("request_timeout_seconds", 12)),
            max_articles_per_source_per_run=int(
                news_parser_raw.get("max_articles_per_source_per_run", 40)
            ),
            max_pages_per_run=int(news_parser_raw.get("max_pages_per_run", 5)),
            bootstrap_articles_per_source=int(
                news_parser_raw.get("bootstrap_articles_per_source", 0)
            ),
            bootstrap_snapshot_path=str(
                news_parser_raw.get(
                    "bootstrap_snapshot_path",
                    "src/parser_common/data/bootstrap_events.jsonl.gz",
                )
            ),
            collect_timeout_seconds=int(news_parser_raw.get("collect_timeout_seconds", 90)),
            insert_batch_size=int(news_parser_raw.get("insert_batch_size", 25)),
            early_stop_known_streak=int(news_parser_raw.get("early_stop_known_streak", 15)),
            source_pause_seconds=float(news_parser_raw.get("source_pause_seconds", 0.5)),
            backfill_pause_seconds=float(news_parser_raw.get("backfill_pause_seconds", 2.0)),
            user_agent=str(
                news_parser_raw.get(
                    "user_agent",
                    "HackMaxNewsBot/1.0 (+https://github.com/hack-max)",
                )
            ),
            sources=_parse_news_sources(news_parser_raw.get("sources")),
        ),
        mc_parser=McParserConfig(
            mode=str(mc_parser_raw.get("mode", "bootstrap")).strip().lower(),
            lookback_days=int(mc_parser_raw.get("lookback_days", 14)),
            poll_interval_seconds=int(mc_parser_raw.get("poll_interval_seconds", 3600)),
            request_timeout_seconds=int(mc_parser_raw.get("request_timeout_seconds", 15)),
            max_articles_per_source_per_run=int(
                mc_parser_raw.get("max_articles_per_source_per_run", 40)
            ),
            max_pages_per_run=int(mc_parser_raw.get("max_pages_per_run", 5)),
            bootstrap_articles_per_source=int(
                mc_parser_raw.get("bootstrap_articles_per_source", 0)
            ),
            collect_timeout_seconds=int(mc_parser_raw.get("collect_timeout_seconds", 120)),
            insert_batch_size=int(mc_parser_raw.get("insert_batch_size", 20)),
            early_stop_known_streak=int(mc_parser_raw.get("early_stop_known_streak", 10)),
            source_pause_seconds=float(mc_parser_raw.get("source_pause_seconds", 0.5)),
            backfill_pause_seconds=float(mc_parser_raw.get("backfill_pause_seconds", 2.0)),
            user_agent=str(
                mc_parser_raw.get(
                    "user_agent",
                    "HackMaxMcBot/1.0 (+https://github.com/hack-max)",
                )
            ),
            sources=_parse_mc_sources(mc_parser_raw.get("sources")),
        ),
        notify=NotifyConfig(
            enabled=bool(notify_raw.get("enabled", False)),
            poll_interval_seconds=int(notify_raw.get("poll_interval_seconds", 30)),
            timezone=str(notify_raw.get("timezone", "Europe/Moscow")),
            digest_hour=int(notify_raw.get("digest_hour", 20)),
            digest_jitter_minutes=int(notify_raw.get("digest_jitter_minutes", 60)),
            digest_min_new_messages=int(notify_raw.get("digest_min_new_messages", 30)),
            retry_interval_seconds=int(notify_raw.get("retry_interval_seconds", 3600)),
            summarizer_provider=(
                str(notify_raw.get("summarizer_provider", "none")).strip().lower()
            ),
            summarizer_timeout_seconds=float(notify_raw.get("summarizer_timeout_seconds", 12.0)),
            summarizer_retry_count=int(notify_raw.get("summarizer_retry_count", 1)),
        ),
        chat_parser=ChatParserConfig(
            enabled=bool(chat_parser_raw.get("enabled", True)),
            min_chars=int(chat_parser_raw.get("min_chars", 3)),
            flood_window_seconds=int(chat_parser_raw.get("flood_window_seconds", 90)),
            flood_max_repeats=int(chat_parser_raw.get("flood_max_repeats", 3)),
            updates_limit=max(1, int(chat_parser_raw.get("updates_limit", 50))),
            greeting_only=_parse_str_list(chat_parser_raw.get("greeting_only")),
            photo_attach_window_seconds=int(
                chat_parser_raw.get("photo_attach_window_seconds", 600)
            ),
        ),
        runtime=RuntimeConfig(
            enable_bot=bool(runtime_raw.get("enable_bot", True)),
            enable_api=bool(runtime_raw.get("enable_api", True)),
            enable_news_parser=bool(runtime_raw.get("enable_news_parser", True)),
            enable_mc_parser=bool(runtime_raw.get("enable_mc_parser", True)),
            enable_chat_parser=bool(runtime_raw.get("enable_chat_parser", True)),
        ),
        docs=DocsConfig(
            url=str(docs_raw.get("url", "https://alexeyv07.github.io/hack_max/docs/")),
            github_url=str(docs_raw.get("github_url", "https://github.com/Alexeyv07/hack_max")),
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    """Сбросить кэш настроек (удобно в тестах)."""
    get_settings.cache_clear()

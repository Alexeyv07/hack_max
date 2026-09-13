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
class Settings:
    environment: str
    app: AppConfig = field(default_factory=AppConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    max: MaxConfig = field(default_factory=MaxConfig)


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
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    """Сбросить кэш настроек (удобно в тестах)."""
    get_settings.cache_clear()

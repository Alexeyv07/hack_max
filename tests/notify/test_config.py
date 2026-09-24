from __future__ import annotations

import os

import project.config as config_module
from project.config import get_settings, reset_settings_cache


def test_notify_loads_from_yaml(monkeypatch) -> None:
    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("APP_ENVIRONMENT", "prod")
    monkeypatch.delenv("NOTIFY_ENABLED", raising=False)
    for key in list(os.environ):
        if key.startswith("NOTIFY__"):
            monkeypatch.delenv(key, raising=False)
    reset_settings_cache()
    try:
        cfg = get_settings().notify
        assert cfg.enabled is False
        assert cfg.digest_hour == 20
        assert cfg.digest_min_new_messages == 30
        assert cfg.retry_interval_seconds == 3600
        assert cfg.summarizer_model == "deepseek-v4-flash-0731"
        assert cfg.summarizer_timeout_seconds == 12.0
        assert cfg.summarizer_retry_count == 1
        assert not hasattr(cfg, "summarizer_provider")
    finally:
        reset_settings_cache()


def test_notify_enabled_env_alias(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "prod")
    monkeypatch.setenv("NOTIFY_ENABLED", "true")
    reset_settings_cache()
    try:
        cfg = get_settings().notify
        assert cfg.enabled is True
    finally:
        reset_settings_cache()

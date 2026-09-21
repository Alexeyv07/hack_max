from __future__ import annotations

from project.config import get_settings, reset_settings_cache


def test_notify_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("NOTIFY_ENABLED", raising=False)
    monkeypatch.delenv("SUMMARIZER_PROVIDER", raising=False)
    reset_settings_cache()
    try:
        cfg = get_settings().notify
        assert cfg.enabled is False
        assert cfg.digest_hour == 20
        assert cfg.digest_top_k == 5
        assert cfg.retry_interval_seconds == 3600
        assert cfg.summarizer_timeout_seconds == 12.0
        assert cfg.summarizer_retry_count == 1
    finally:
        reset_settings_cache()


def test_notify_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("NOTIFY_ENABLED", "true")
    monkeypatch.setenv("SUMMARIZER_PROVIDER", "deepseek")
    reset_settings_cache()
    try:
        cfg = get_settings().notify
        assert cfg.enabled is True
        assert cfg.summarizer_provider == "deepseek"
    finally:
        reset_settings_cache()

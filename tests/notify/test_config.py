from __future__ import annotations

from project.config import get_settings, reset_settings_cache


def test_notify_enabled_env_alias(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "prod")
    monkeypatch.setenv("NOTIFY_ENABLED", "false")
    reset_settings_cache()
    try:
        cfg = get_settings().notify
        assert cfg.enabled is False
    finally:
        reset_settings_cache()

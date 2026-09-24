from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx

from notify.chat_source import ChatMessage
from notify.summarizer import summarize_digest
from project.config import NotifyConfig


def _messages() -> list[ChatMessage]:
    start = datetime(2026, 9, 21, 16, tzinfo=UTC)
    return [
        ChatMessage("Соседи, воду отключили до 18:00", start),
        ChatMessage("У второго подъезда работает аварийная служба", start + timedelta(minutes=1)),
        ChatMessage("После 18:00 обещали всё включить", start + timedelta(minutes=2)),
    ]


def _response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            "- Воду отключили до 18:00.\n"
                            "- У второго подъезда работает аварийная служба.\n"
                            "- После 18:00 воду обещали включить."
                        )
                    }
                }
            ]
        },
    )


def test_missing_api_key_skips_network(monkeypatch) -> None:
    monkeypatch.delenv("AITUNNEL_API_KEY", raising=False)
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response()

    result = asyncio.run(
        summarize_digest(
            _messages(),
            config=NotifyConfig(),
            transport=httpx.MockTransport(handler),
        )
    )

    assert result is None
    assert calls == 0


def test_aitunnel_prompt_contains_only_chat_texts(monkeypatch) -> None:
    monkeypatch.setenv("AITUNNEL_API_KEY", "aitunnel-secret")
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return _response()

    result = asyncio.run(
        summarize_digest(
            _messages(),
            config=NotifyConfig(),
            transport=httpx.MockTransport(handler),
        )
    )

    assert result is not None
    payload = seen["payload"]
    assert isinstance(payload, dict)
    prompt = payload["messages"][1]["content"]
    for message in _messages():
        assert message.text in prompt
    for forbidden in ("event_id", "importance", "weight", "address", "user_id", "chat_id", "2026"):
        assert forbidden not in prompt


def test_aitunnel_uses_config_model_and_reasoning_budget(monkeypatch) -> None:
    monkeypatch.setenv("AITUNNEL_API_KEY", "aitunnel-secret")
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["payload"] = json.loads(request.content)
        return _response()

    result = asyncio.run(
        summarize_digest(
            _messages(),
            config=NotifyConfig(summarizer_model="deepseek-v4-flash-0731"),
            transport=httpx.MockTransport(handler),
        )
    )

    assert result is not None
    assert seen["url"] == "https://api.aitunnel.ru/v1/chat/completions"
    assert seen["authorization"] == "Bearer aitunnel-secret"
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "deepseek-v4-flash-0731"
    assert payload["max_tokens"] == 1000
    assert payload["reasoning"] == {"effort": "minimal", "exclude": True}


def test_summarizer_retries_then_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("AITUNNEL_API_KEY", "secret")
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "busy"})
        return _response()

    result = asyncio.run(
        summarize_digest(
            _messages(),
            config=NotifyConfig(
                summarizer_retry_count=1,
                summarizer_timeout_seconds=10,
            ),
            transport=httpx.MockTransport(handler),
        )
    )

    assert result is not None
    assert calls == 2


def test_invalid_llm_output_falls_back_to_none(monkeypatch) -> None:
    monkeypatch.setenv("AITUNNEL_API_KEY", "secret")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Один длинный абзац без буллетов"}}]},
        )

    result = asyncio.run(
        summarize_digest(
            _messages(),
            config=NotifyConfig(summarizer_retry_count=0),
            transport=httpx.MockTransport(handler),
        )
    )

    assert result is None

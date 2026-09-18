#!/usr/bin/env python3
"""Печатает публичный HTTPS URL ngrok (инспектор http://127.0.0.1:4040)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def main() -> int:
    url = "http://127.0.0.1:4040/api/tunnels"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.load(resp)
    except urllib.error.URLError as exc:
        print(
            f"ngrok inspector недоступен на :4040 — поднимите: docker compose up -d ngrok\n({exc})",
            file=sys.stderr,
        )
        return 1

    tunnels = payload.get("tunnels") or []
    https = [
        t.get("public_url") for t in tunnels if str(t.get("public_url", "")).startswith("https://")
    ]
    if not https:
        # fallback: любой public_url
        https = [t.get("public_url") for t in tunnels if t.get("public_url")]

    if not https:
        print("Туннелей пока нет — подождите пару секунд и повторите.", file=sys.stderr)
        return 2

    for item in https:
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

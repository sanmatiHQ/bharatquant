"""
Healthcheck utilities: token, DB, endpoints.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import httpx

_token_cache: dict[str, object] = {"ts": 0.0, "ok": False}


def check_token_fast() -> bool:
    """Dashboard fast path — use cache or token file only; no Kite HTTP."""
    now = time.time()
    if now - float(_token_cache["ts"]) < 300:
        return bool(_token_cache["ok"])
    path = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        token = data.get("access_token")
        if not token and isinstance(data.get("data"), dict):
            token = data["data"].get("access_token")
        return bool(token)
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def check_token(*, live: bool = True) -> bool:
    """Return True only if access token exists and validates against Kite REST."""
    now = time.time()
    if live and now - float(_token_cache["ts"]) < 60:
        return bool(_token_cache["ok"])
    path = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        token = data.get("access_token")
        if not token and isinstance(data.get("data"), dict):
            token = data["data"].get("access_token")
        if not token:
            if live:
                _token_cache.update({"ts": now, "ok": False})
            return False
        if not live:
            return True
        api_key = os.getenv("KITE_API_KEY", "")
        if not api_key:
            return False
        r = httpx.get(
            "https://api.kite.trade/user/profile",
            headers={"X-Kite-Version": "3", "Authorization": f"token {api_key}:{token}"},
            timeout=2.0,
        )
        ok = r.status_code == 200
        _token_cache.update({"ts": now, "ok": ok})
        return ok
    except (FileNotFoundError, json.JSONDecodeError, httpx.HTTPError):
        if live:
            _token_cache.update({"ts": now, "ok": False})
        return False


def token_age_hours() -> float | None:
    path = Path(os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json"))
    if not path.exists():
        return None
    return (time.time() - path.stat().st_mtime) / 3600.0


def check_db() -> bool:
    path = os.getenv("SQLITE_PATH", "data/trading.db")
    try:
        con = sqlite3.connect(path)
        con.execute("SELECT 1")
        con.close()
        return True
    except Exception:
        return False


def check_endpoints() -> dict:
    base = "http://localhost:8080/api"
    results = {}
    for ep in [
        "overview",
        "positions",
        "trades",
        "screening",
        "market-updates",
        "stock-search?q=INFY",
        "logs",
    ]:
        try:
            r = httpx.get(f"{base}/{ep}", timeout=2)
            results[ep] = r.status_code
        except Exception:
            results[ep] = None
    return results

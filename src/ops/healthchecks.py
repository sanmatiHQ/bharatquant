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


def check_token(*, live: bool = True) -> bool:
    """Return True only if access token exists and validates against Kite REST."""
    path = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        token = data.get("access_token")
        if not token and isinstance(data.get("data"), dict):
            token = data["data"].get("access_token")
        if not token:
            return False
        if not live:
            return True
        api_key = os.getenv("KITE_API_KEY", "")
        if not api_key:
            return False
        r = httpx.get(
            "https://api.kite.trade/user/profile",
            headers={"X-Kite-Version": "3", "Authorization": f"token {api_key}:{token}"},
            timeout=10,
        )
        return r.status_code == 200
    except (FileNotFoundError, json.JSONDecodeError, httpx.HTTPError):
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

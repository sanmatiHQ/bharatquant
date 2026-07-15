"""New dashboard endpoints: indices, search, suggest-to-agent queue, Kite status.

Suggestion endpoints are admin-gated (owner action, not public write) — same pattern
as /api/halt. The suggest flow must not bypass any gate: verified here that it only
creates a 'pending' row and a real Signal, never a direct trade.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.api.dashboard import create_app
from src.db.database import DB, DBConfig
from src.events.types import EventType, MarketEvent
from src.strategies.base import MarketContext


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DASHBOARD_ADMIN_USER", "owner")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret123")
    return TestClient(create_app())


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t2.db"))
    return DB(DBConfig(sqlite_path=str(tmp_path / "t2.db")))


def _login(client):
    r = client.post("/api/admin/login", json={"username": "owner", "password": "secret123"})
    assert r.status_code == 200


def test_indices_endpoint_reports_stale_without_data(client):
    r = client.get("/api/indices")
    assert r.status_code == 200
    body = r.json()
    keys = {row["key"] for row in body}
    assert {"nifty50", "nifty100", "banknifty", "sensex"} <= keys
    for row in body:
        assert row["stale"] is True  # no tick data seeded — must say so honestly, not fabricate

    sensex = next(row for row in body if row["key"] == "sensex")
    assert sensex["exchange"] == "BSE"


def test_search_endpoint_public_no_auth(client):
    r = client.get("/api/search/RELIANCE")
    assert r.status_code == 200
    assert "symbol" in r.json() or "signals" in r.json() or isinstance(r.json(), dict)


def test_suggest_requires_admin(client):
    r = client.post("/api/manual_trade/suggest", json={"symbol": "TCS", "side": "BUY", "thesis": "test"})
    assert r.status_code == 401


def test_suggest_creates_pending_row_not_a_trade(client):
    _login(client)
    r = client.post("/api/manual_trade/suggest", json={"symbol": "TCS", "side": "BUY", "thesis": "breaking out"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "pending"

    r2 = client.get("/api/manual_trade/queue")
    assert r2.status_code == 200
    rows = r2.json()
    assert any(row["symbol"] == "TCS" and row["status"] == "pending" for row in rows)


def test_queue_requires_admin(client):
    r = client.get("/api/manual_trade/queue")
    assert r.status_code == 401


def test_kite_status_public_and_honest_when_no_token_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("KITE_ACCESS_TOKEN_FILE", str(tmp_path / "nope.json"))
    r = client.get("/api/kite/status")
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert body["refreshed_at"] is None


def test_reauth_requires_admin(client):
    r = client.post("/api/kite/reauth")
    assert r.status_code == 401


# ---------- UserSuggestionStrategy: proves no bypass ----------


@pytest.mark.asyncio
async def test_user_suggestion_strategy_emits_signal_not_a_trade(db):
    from src.ops.manual_trade import create_suggestion, list_suggestions
    from src.strategies.candidacy_signals import UserSuggestionStrategy

    create_suggestion(db, "TCS", "BUY", "breaking out above resistance")
    strat = UserSuggestionStrategy(db=db)
    event = MarketEvent(type=EventType.BAR_CLOSE_5M, symbol="NSE:TCS", price=3800.0)
    sig = await strat.on_event(event, MarketContext())

    assert sig is not None
    assert sig.strategy_id == "user_suggested"
    assert sig.action == "BUY"
    # no trade was placed — only a Signal was returned, same as any other strategy
    trades = db._conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]
    assert trades == 0

    rows = list_suggestions(db)
    assert rows[0]["status"] == "evaluating"


@pytest.mark.asyncio
async def test_user_suggestion_strategy_silent_with_no_pending(db):
    from src.strategies.candidacy_signals import UserSuggestionStrategy

    strat = UserSuggestionStrategy(db=db)
    event = MarketEvent(type=EventType.BAR_CLOSE_5M, symbol="NSE:INFY", price=1500.0)
    sig = await strat.on_event(event, MarketContext())
    assert sig is None


def test_resolve_evaluating_suggestions_expires_stale_ones(db):
    from src.ops.manual_trade import (
        create_suggestion,
        list_suggestions,
        mark_suggestion_evaluating,
        resolve_evaluating_suggestions,
    )

    res = create_suggestion(db, "WIPRO", "BUY", "")
    mark_suggestion_evaluating(db, res["id"])
    # backdate so it looks stale
    with db.tx() as conn:
        conn.execute("UPDATE user_suggestions SET ts=? WHERE id=?", (int(time.time()) - 2000, res["id"]))

    n = resolve_evaluating_suggestions(db, stale_after_sec=900)
    assert n == 1
    rows = list_suggestions(db)
    assert rows[0]["status"] == "expired_no_signal_window"


def test_new_strategies_default_to_candidacy_including_user_suggested(db):
    from src.agent.strategy_lifecycle import ensure_lifecycle_row

    assert ensure_lifecycle_row(db, "user_suggested") == "candidacy"

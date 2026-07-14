"""Capital gate and fitness evidence tests."""
from __future__ import annotations

import time

import pytest

from src.db.database import DB, DBConfig
from src.ops.capital_gate import evaluate_capital_gate, live_mode_allowed
from src.ops.fitness_evidence import (
    clock_start_ts,
    closed_sell_returns,
    ensure_capital_clock,
    reset_capital_clock,
    system_fitness_snapshot,
)
from src.ops.session_state import entries_allowed, normalize_nse_status, set_session_phase
from src.ops.trading_config import resolved_trading_mode


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    return DB(DBConfig(sqlite_path=str(tmp_path / "cap.db")))


def test_capital_gate_blocks_live_by_default(db, monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    allowed, reason, gate = live_mode_allowed(db)
    assert not allowed
    assert "capital_gate" in reason
    assert not gate["eligible"]


def test_capital_gate_not_sticky(db, monkeypatch):
    monkeypatch.setenv("CAPITAL_MIN_CLOSED_TRADES", "2")
    monkeypatch.setenv("CAPITAL_MIN_TRADING_WEEKS", "0")
    monkeypatch.setenv("CAPITAL_MIN_COMPOSITE", "0")
    monkeypatch.setenv("CAPITAL_MIN_PROMOTED_FULL", "0")
    ts = int(time.time())
    for i in range(3):
        db.record_trade(ts + i, "INFY", "SELL", 1, 100.0 + i, 100.0 + i, "test", 0.0, "NA")
    gate = evaluate_capital_gate(db)
    assert gate["checks"]["closed_trades"]["pass"]


def test_clock_reset_on_drawdown_breach(db, monkeypatch):
    monkeypatch.setenv("CAPITAL_MAX_DRAWDOWN_PCT", "5")
    start = ensure_capital_clock(db, start_ts=int(time.time()) - 86400)
    ts = int(time.time())
    for i in range(6):
        db.record_trade(ts + i, "INFY", "SELL", 1, 100.0, 100.0, "test", 0.0, "NA")
    db.snapshot_portfolio(ts - 3600, 100000, 0, 100000, 0, 0, 0)
    db.snapshot_portfolio(ts, 100000, 0, 85000, 0, 0, 20)
    evaluate_capital_gate(db)
    assert clock_start_ts(db) >= start


def test_session_gate_open_only():
    set_session_phase("CLOSED")
    assert not entries_allowed()
    set_session_phase("OPEN")
    assert entries_allowed()


def test_normalize_nse_status_variants():
    assert normalize_nse_status("Pre-Open") == "PRE_OPEN"
    assert normalize_nse_status("Open") == "OPEN"
    assert normalize_nse_status("Close") == "CLOSED"


def test_trading_mode_defaults_paper(monkeypatch):
    monkeypatch.delenv("TRADING_MODE", raising=False)
    assert resolved_trading_mode() == "paper"


def test_fitness_snapshot_empty_db(db):
    snap = system_fitness_snapshot(db)
    assert snap["closed_sells"] == 0
    assert snap["composite"] == 0.0

"""Effective-N correlation correction for the capital gate. Community lesson:
"n=1,235 is really n=a-lot-less" once correlated instruments are accounted for
— trades clustered on the same symbol aren't independent evidence.
"""
from __future__ import annotations

import time

import pytest

from src.db.database import DB, DBConfig
from src.ops.capital_gate import evaluate_capital_gate
from src.ops.fitness_evidence import effective_sample_size, system_fitness_snapshot


@pytest.fixture
def db(tmp_path):
    return DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))


def test_fully_diversified_trades_barely_discounted():
    # 10 trades, 10 distinct symbols -> no clustering, no real discount
    rets = [(f"SYM{i}", 0.01) for i in range(10)]
    n_eff = effective_sample_size(rets)
    assert n_eff == pytest.approx(10.0)


def test_fully_clustered_trades_heavily_discounted():
    # 10 trades, all on ONE symbol -> sqrt(10), not 10
    rets = [("TCS", 0.01) for _ in range(10)]
    n_eff = effective_sample_size(rets)
    assert n_eff == pytest.approx(10 ** 0.5, rel=0.01)
    assert n_eff < 4.0  # much less than the raw count of 10


def test_mixed_clustering():
    # 20 trades: 15 on one symbol, 5 spread across 5 distinct symbols
    rets = [("TCS", 0.01)] * 15 + [(f"SYM{i}", 0.01) for i in range(5)]
    n_eff = effective_sample_size(rets)
    expected = (15 ** 0.5) + 5 * (1 ** 0.5)
    assert n_eff == pytest.approx(expected, rel=0.01)
    assert n_eff < 20.0


def test_empty_returns_zero_effective_n():
    assert effective_sample_size([]) == 0.0


def test_capital_gate_rejects_raw_count_that_clears_only_via_clustering(db, monkeypatch):
    """The actual point of this fix: a raw closed-trade count that clears the
    threshold, but only because it's almost all one correlated symbol, must NOT
    pass the go-live gate."""
    monkeypatch.setenv("CAPITAL_MIN_CLOSED_TRADES", "10")
    monkeypatch.setenv("CAPITAL_MIN_TRADING_WEEKS", "0")
    monkeypatch.setenv("CAPITAL_MIN_COMPOSITE", "0")
    monkeypatch.setenv("CAPITAL_MIN_PROMOTED_FULL", "0")
    ts = int(time.time())
    # 12 raw closed trades, ALL on PPAP — clears raw threshold (12>=10) but
    # effective N = sqrt(12) ~= 3.46, nowhere near 10.
    for i in range(12):
        db.record_trade(ts + i, "PPAP", "SELL", 1, 100.0 + i * 0.1, 100.0 + i * 0.1, "test", 0.0, "NA")
    gate = evaluate_capital_gate(db)
    check = gate["checks"]["closed_trades"]
    assert check["raw_value"] == 12
    assert check["value"] < 4.0  # effective, not raw
    assert not check["pass"], "12 raw trades all on one symbol must not clear a 10-independent-trade bar"


def test_capital_gate_passes_genuinely_diversified_count(db, monkeypatch):
    monkeypatch.setenv("CAPITAL_MIN_CLOSED_TRADES", "10")
    monkeypatch.setenv("CAPITAL_MIN_TRADING_WEEKS", "0")
    monkeypatch.setenv("CAPITAL_MIN_COMPOSITE", "0")
    monkeypatch.setenv("CAPITAL_MIN_PROMOTED_FULL", "0")
    ts = int(time.time())
    symbols = ["TCS", "INFY", "WIPRO", "HDFCBANK", "RELIANCE", "SBIN", "ITC", "ONGC", "LT", "AXISBANK", "M&M", "TITAN"]
    for i, sym in enumerate(symbols):
        db.record_trade(ts + i, sym, "SELL", 1, 100.0 + i, 100.0 + i, "test", 0.0, "NA")
    gate = evaluate_capital_gate(db)
    check = gate["checks"]["closed_trades"]
    assert check["raw_value"] == 12
    assert check["value"] == pytest.approx(12.0)  # no clustering -> no discount
    assert check["pass"]


def test_fitness_snapshot_exposes_both_raw_and_effective(db):
    ts = int(time.time())
    for i in range(5):
        db.record_trade(ts + i, "TCS", "SELL", 1, 100.0, 100.0, "test", 0.0, "NA")
    snap = system_fitness_snapshot(db, ts - 10)
    assert snap["closed_sells"] == 5
    assert snap["effective_closed_trades"] == pytest.approx(5 ** 0.5, abs=0.05)  # snapshot rounds to 1dp
    assert snap["effective_closed_trades"] < snap["closed_sells"]

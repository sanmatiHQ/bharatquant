"""Tests for holistic fast snapshot decisions."""
from __future__ import annotations

import os
import time

import pytest

from src.db.database import DB, DBConfig
from src.engine.fast_snapshot import build_holistic_signal, is_fast_path_enabled
from src.strategies.base import MarketContext


def test_fast_path_enabled_default():
    os.environ["FAST_PATH_ENTRIES"] = "true"
    assert is_fast_path_enabled() is True


def test_build_holistic_signal_picks_affordable(tmp_path):
    os.environ["MAX_RUPEES_PER_TRADE"] = "2000"
    db = DB(DBConfig(sqlite_path=str(tmp_path / "fast.db")))
    ts = int(time.time())
    run_ts = ts - 60
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO screening_results(run_ts, symbol, momentum_score) VALUES (?,?,?)",
            (run_ts, "INFY", 0.95),
        )
        conn.execute(
            "INSERT INTO screening_results(run_ts, symbol, momentum_score) VALUES (?,?,?)",
            (run_ts, "SBIN", 0.99),
        )
        conn.execute(
            "INSERT INTO screening_results(run_ts, symbol, momentum_score) VALUES (?,?,?)",
            (run_ts, "TITAN", 0.85),
        )
        conn.execute("INSERT INTO tick_log(ts, symbol, ltp) VALUES (?,?,?)", (ts, "SBIN", 150.0))
        conn.execute("INSERT INTO tick_log(ts, symbol, ltp) VALUES (?,?,?)", (ts, "TITAN", 4610.0))
        conn.execute(
            """
            INSERT INTO bar_log(ts, symbol, interval, open, high, low, close, volume)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (ts - 3600, "SBIN", "5m", 148.0, 152, 147, 150.0, 1000),
        )
        conn.execute("INSERT INTO cash_ledger(ts, delta, note) VALUES (?,?,?)", (ts, 10000, "seed"))
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("budget_rolled_inr", "2000"),
        )
    os.environ["BUDGET_ROLLOVER_MODE"] = "accumulate"
    os.environ["DAILY_INVESTMENT_MAX"] = "2000"
    ctx = MarketContext(fii_net_cr=600, gift_nifty_change_pct=0.2)
    picked = build_holistic_signal(db, ctx)
    assert picked is not None
    sig, ltp = picked
    assert sig.symbol == "SBIN"
    assert sig.strategy_id == "fast_snapshot"
    assert ltp == 150.0


def test_build_holistic_signal_obi_boost(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "obi.db")))
    ts = int(time.time())
    run_ts = ts - 60
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO screening_results(run_ts, symbol, momentum_score) VALUES (?,?,?)",
            (run_ts, "SBIN", 0.8),
        )
        conn.execute("INSERT INTO tick_log(ts, symbol, ltp) VALUES (?,?,?)", (ts, "SBIN", 150.0))
        conn.execute("INSERT INTO cash_ledger(ts, delta, note) VALUES (?,?,?)", (ts, 10000, "seed"))
    ctx = MarketContext()
    ctx.orderbook_imbalance["SBIN"] = 0.6
    ctx.tick_atr_bps["SBIN"] = 10.0
    picked = build_holistic_signal(db, ctx)
    assert picked is not None
    assert "obi=" in picked[0].reason

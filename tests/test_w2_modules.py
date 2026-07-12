from __future__ import annotations

import time

from src.accounting.fifo_lots import close_lots_fifo, open_lot
from src.costs.cost_engine import CostEngine
from src.db.database import DB, DBConfig
from src.agent.regime_classifier import classify_regime, regime_strategy_whitelist
from src.risk.event_calendar import seed_calendar_year, today_risk_level, mis_allowed_today
from src.agent.kelly_sizing import kelly_fraction
from src.agent.var_breaker import historical_var


def test_fifo_roundtrip(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "f.db")))
    db.add_cash(1, 50_000.0, "seed")
    ts = int(time.time())
    open_lot(db, "INFY", 10, 100.0, ts, "CNC", 1)
    fills, tax = close_lots_fifo(db, "INFY", 10, 110.0, ts + 86400 * 10, CostEngine(0))
    assert len(fills) == 1
    assert tax == "STCG"
    assert fills[0].pnl == 100.0


def test_regime_classifier():
    r = classify_regime([0.002] * 20, vix=15)
    assert r.label in ("BULL", "BEAR", "SIDEWAYS", "HIGH_VOL")
    wl = regime_strategy_whitelist("BULL")
    assert "combined_momentum" in wl


def test_event_calendar(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "c.db")))
    n = seed_calendar_year(db, 2026)
    assert n >= 5
    assert today_risk_level(db) in ("low", "medium", "high")
    assert isinstance(mis_allowed_today(db), bool)


def test_kelly_and_var():
    k = kelly_fraction(0.6, 1.5, 1.0)
    assert 0 <= k <= 1
    v = historical_var([0.01, -0.02, 0.005, -0.03, 0.01] * 5)
    assert v >= 0

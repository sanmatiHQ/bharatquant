"""Tests for pre/post market routines and VIX controls."""
from __future__ import annotations

import json
import os

import pytest

from src.db.database import DB, DBConfig
from src.ops.agent_state import persist_context, persist_decision
from src.ops.budget_gate import approved_daily_max, auto_approve_budget_if_vix_safe
from src.ops.slippage_analysis import analyze_today_slippage
from src.ops.vix_controls import (
    llm_bearish_veto_threshold,
    vix_adjusted_stop_pct,
    vix_safe_for_budget,
    vix_sizing_scale,
)
from src.risk.risk_engine import RiskConfig, RiskEngine


class _Ctx:
    fii_net_cr = 120.0
    dii_net_cr = 0.0
    gift_nifty_change_pct = 0.8
    india_vix = 14.0
    futures_oi_chg = 0.0
    llm_bias = 0.0


def test_vix_budget_auto_approve_safe(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "vix.db")))
    persist_context(db, _Ctx())
    r = auto_approve_budget_if_vix_safe(db)
    assert r["ok"] is True
    assert approved_daily_max(db) == float(os.getenv("DAILY_INVESTMENT_MAX", "2000"))


def test_vix_budget_blocks_high_vol(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "vix2.db")))
    ctx = _Ctx()
    ctx.india_vix = 28.0
    persist_context(db, ctx)
    r = auto_approve_budget_if_vix_safe(db)
    assert r["ok"] is False


def test_vix_sizing_and_stop_tighten():
    assert vix_sizing_scale(14) == 1.0
    assert vix_sizing_scale(24) < 0.6
    assert vix_adjusted_stop_pct(2.5, 14) == 2.5
    assert vix_adjusted_stop_pct(2.5, 24) < 2.0


def test_risk_engine_vix_stop():
    eng = RiskEngine(RiskConfig(2.5, 2, 2000, 8))
    state = {"avg_price": 100, "last_price": 97.5, "open_ts": 0, "rail": "MIS"}
    ok, reason = eng.should_exit(state, india_vix=24)
    assert ok is True
    assert "stop_loss" in reason


def test_slippage_analysis(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "slip.db")))
    import time

    ts = int(time.time())
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO strategy_ledger(ts, strategy_id, symbol, event_type, signal, confidence, price, executed, reason)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (ts - 5, "fast_snapshot", "INFY", "FAST_SNAPSHOT", "BUY", 0.8, 100.0, 1, "test"),
        )
    db.record_trade(ts, "INFY", "BUY", 1, 100.5, 100.5, "test", 0, "NA")
    summary = analyze_today_slippage(db)
    assert summary["trade_count"] == 1
    assert summary["rows"][0]["target_price"] == 100.0


@pytest.mark.asyncio
async def test_premarket_persists_decision(tmp_path, monkeypatch):
    from src.ops.market_routines import run_premarket_routine

    db = DB(DBConfig(sqlite_path=str(tmp_path / "pre.db")))
    persist_context(db, _Ctx())
    monkeypatch.setenv("LLM_ENABLED", "false")

    async def fake_bias(db, ctx):
        return 0.65

    monkeypatch.setattr("src.ingest.llm_macro.compute_llm_bias", fake_bias)
    result = await run_premarket_routine(db, _Ctx())
    assert result["ok"] is True
    row = db._conn.execute("SELECT v FROM settings WHERE k='agent_last_decision'").fetchone()
    dec = json.loads(row["v"])
    assert dec["action"] == "PREMARKET"
    assert "Bias set to" in dec["reason"]

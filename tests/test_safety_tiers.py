"""Tier 0–3 safety and infrastructure tests."""
from __future__ import annotations

import time

from unittest.mock import patch

import pytest

from src.agent.router import AgentRouter
from src.agent.strategy_lifecycle import ensure_lifecycle_row, evaluate_lifecycle_transitions, migrate_grandfather_existing
from src.db.database import DB, DBConfig
from src.ops.budget_gate import can_deploy, set_setting, approved_daily_max
from src.ops.loss_ledger import record_closed_loss, structural_loss_count
from src.ops.slippage_parity import record_slippage_pair, running_bias
from src.ops.symbol_session_cooldown import can_reenter_symbol, record_losing_close
from src.strategies.base import Signal


@pytest.fixture
def db(tmp_path):
    return DB(DBConfig(sqlite_path=str(tmp_path / "tier.db")))


def test_budget_hard_block_via_risk_veto(db):
    set_setting(db, "daily_budget_max_approved", str(approved_daily_max(db)))
    db.record_trade(int(time.time()), "INFY", "BUY", 1, 100.0, 2000.0, "seed", 0, "NA")
    router = AgentRouter(db=db)
    sig = Signal("connors_ibs", "INFY", "BUY", "CNC", 0.9, "test")
    with patch("src.agent.router.rupees_from_kelly", return_value=800.0):
        ok, reason = router.risk_veto(sig, {"total_equity": 500000, "cash": 400000})
    assert not ok
    assert "budget" in reason or "daily_budget" in reason


def test_symbol_loss_cooldown_blocks_reentry(db):
    record_losing_close(db, "PPAP", -120.0, "signal_combiner")
    ok, reason = can_reenter_symbol(
        db, "PPAP", strategy_id="signal_combiner", confidence=0.7
    )
    assert not ok
    assert "cooldown" in reason


def test_symbol_cooldown_override_different_strategy(db):
    record_losing_close(db, "PPAP", -50.0, "signal_combiner")
    ok, _ = can_reenter_symbol(
        db, "PPAP", strategy_id="connors_ibs", confidence=0.92
    )
    assert ok


def test_grandfather_core_strategies(db):
    n = migrate_grandfather_existing(db)
    assert n >= 30
    assert ensure_lifecycle_row(db, "connors_ibs") == "full"
    assert ensure_lifecycle_row(db, "index_reconstitution") == "candidacy"


def test_new_candidacy_strategy_defaults(db):
    assert ensure_lifecycle_row(db, "pead_continuation") == "candidacy"


def test_structural_loss_ledger(db):
    record_closed_loss(
        db,
        trade_id=1,
        symbol="PPAP",
        strategy_id="signal_combiner",
        pnl_inr=-80,
        regime_entry="BEAR",
        regime_exit="BEAR",
        stop_designed=True,
        stop_slipped=True,
        slippage_inr=40,
        slippage_bps=50,
        signal_failure_pct=30,
        cost_drag_pct=70,
    )
    assert structural_loss_count(db, "signal_combiner") >= 1


def test_slippage_parity_running_bias(db):
    record_slippage_pair(
        db,
        symbol="INFY",
        side="BUY",
        predicted_price=100.0,
        actual_price=100.5,
        qty=10,
        strategy_id="connors_ibs",
    )
    bias = running_bias(db)
    assert bias["n"] >= 1
    assert bias["mean_signed_bps"] != 0


def test_can_deploy_blocks_over_cap(db):
    db.record_trade(int(time.time()), "TCS", "BUY", 1, 100.0, 2500.0, "x", 0, "NA")
    ok, reason = can_deploy(db, 500.0)
    assert not ok
    assert "daily_budget_cap" in reason

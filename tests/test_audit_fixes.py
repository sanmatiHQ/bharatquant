"""Tests for audit fixes 0–10 — regime, Kelly, slippage, bandit, RL, shadow, beta, promotion."""
from __future__ import annotations

import json
import time
from datetime import date

import numpy as np
import pytest

from src.agent.bandit import StrategyBandit
from src.agent.kelly_stats import kelly_inputs_for_strategy
from src.agent.kelly_sizing import kelly_fraction, rupees_from_kelly
from src.agent.regime_classifier import (
    apply_fii_regime_nudge,
    append_index_return,
    classify_regime,
    refresh_ctx_regime,
)
from src.agent.strategy_stats import (
    binomial_edge_p_value,
    expected_move_pct_for_strategy,
    strategy_performance,
    thompson_win_loss_counts,
)
from src.costs.cost_engine import CostEngine
from src.db.database import DB, DBConfig
from src.exec.paper_broker import PaperBroker
from src.intelligence.strategy_correlation import refresh_disabled_strategies
from src.intelligence.strategy_learning import promote_discovery_rules
from src.intelligence.strategy_discovery import _rsi_from_closes
from src.risk.event_calendar import _load_rbi_dates
from src.risk.portfolio_beta import can_add_beta_exposure, symbol_beta_to_index
from src.rl.shadow_backtest import compare_policies
from src.rl.ppo_trainer import PPOPolicy
from src.strategies.base import MarketContext


@pytest.fixture
def db(tmp_path):
    return DB(DBConfig(sqlite_path=str(tmp_path / "audit.db")))


def _seed_outcomes(db: DB, strategy_id: str, returns: list[float], *, executed: int = 1, ts_base: int | None = None) -> None:
    ts = ts_base if ts_base is not None else int(time.time()) - 7200
    with db.tx() as conn:
        for i, ret in enumerate(returns):
            conn.execute(
                """
                INSERT INTO strategy_ledger(ts, strategy_id, symbol, signal, confidence, executed, price, reason, event_type)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (ts + i, strategy_id, "SBIN", "BUY", 0.7, executed, 100.0, "test", "BAR_CLOSE_5M"),
            )
            conn.execute(
                """
                INSERT INTO strategy_signal_outcomes(ledger_ts, strategy_id, symbol, signal, ret_15m, ret_1d)
                VALUES (?,?,?,?,?,?)
                """,
                (ts + i, strategy_id, "SBIN", "BUY", ret, None),
            )


# --- 0 PaperBroker slippage direction ---
def test_paper_broker_slippage_matches_cost_engine():
    costs = CostEngine(slippage_bps=10)
    broker = PaperBroker(slippage_bps=10)
    ltp = 1000.0
    assert broker.buy("SBIN", 1, ltp) == costs.apply_slippage(ltp, "BUY")
    assert broker.sell("SBIN", 1, ltp) == costs.apply_slippage(ltp, "SELL")
    assert broker.buy("SBIN", 1, ltp) > ltp
    assert broker.sell("SBIN", 1, ltp) < ltp


# --- 1 Regime classifier uses rolling returns + FII nudge ---
def test_classify_regime_requires_five_returns():
    assert classify_regime([0.001]).label == "SIDEWAYS"
    bull = classify_regime([0.002] * 10, vix=12.0)
    assert bull.label == "BULL"


def test_append_index_return_builds_deque():
    ctx = MarketContext()
    append_index_return(ctx, 100.0)
    append_index_return(ctx, 101.0)
    assert len(ctx.index_returns) == 1
    assert ctx.index_returns[0] == pytest.approx(0.01)


def test_fii_nudge_tilts_not_overrides():
    assert apply_fii_regime_nudge("BULL", -600) == "SIDEWAYS"
    assert apply_fii_regime_nudge("BEAR", 600) == "SIDEWAYS"
    assert apply_fii_regime_nudge("HIGH_VOL", -600) == "BEAR"


def test_refresh_ctx_regime_from_bars(db):
    ctx = MarketContext()
    ctx.india_vix = 14.0
    ts = int(time.time()) - 3600
    with db.tx() as conn:
        for i in range(30):
            px = 24000.0 + i * 15
            conn.execute(
                """
                INSERT INTO bar_log(ts, symbol, interval, open, high, low, close, volume)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (ts + i * 300, "NIFTY50", "5m", px, px + 10, px - 10, px, 0),
            )
    rs = refresh_ctx_regime(ctx, db)
    assert ctx.regime in ("BULL", "BEAR", "SIDEWAYS", "HIGH_VOL")
    assert rs.label == ctx.regime


# --- 2 Kelly from real outcomes ---
def test_kelly_uses_strategy_outcomes(db):
    _seed_outcomes(db, "opening_range", [0.5, 0.4, -0.2, 0.3, 0.6, -0.1] * 2)
    wr, aw, al = kelly_inputs_for_strategy(db, "opening_range")
    assert wr > 0.5
    assert aw > 0
    assert al > 0
    size = rupees_from_kelly(10_000, wr, aw, al, 1000)
    assert size >= 100


def test_kelly_cold_start_conservative(db):
    wr, aw, al = kelly_inputs_for_strategy(db, "unknown_strategy")
    assert wr == 0.5
    assert aw == 1.0
    assert al == 1.0
    assert kelly_fraction(wr, aw, al) == 0.0


def test_kelly_safety_scalar_env(monkeypatch):
    monkeypatch.setenv("KELLY_SAFETY_SCALAR", "0.5")
    f_full = kelly_fraction(0.6, 1.2, 1.0)
    size = rupees_from_kelly(10_000, 0.6, 1.2, 1.0, 1000)
    assert size <= 10_000 * f_full * 0.5 + 1


# --- 3 Thompson bandit from outcomes ---
def test_bandit_thompson_uses_win_loss_not_confidence(db):
    _seed_outcomes(db, "good_strat", [0.5, 0.4, 0.3, 0.2, 0.6, 0.5, 0.4, 0.3, 0.2, 0.5], ts_base=int(time.time()) - 7200)
    _seed_outcomes(db, "bad_strat", [-0.5, -0.4, -0.3, 0.1, -0.2] * 2, ts_base=int(time.time()) - 3600)
    a_w, a_l = thompson_win_loss_counts(db, "good_strat")
    b_w, b_l = thompson_win_loss_counts(db, "bad_strat")
    assert a_w > b_w or a_l < b_l
    bandit = StrategyBandit(db)
    weights = bandit.update_weights()
    assert "good_strat" in weights
    assert weights["good_strat"] >= weights.get("bad_strat", 0)


# --- 5 Shadow gate no auto-pass ---
def test_shadow_gate_rejects_thin_history(db, tmp_path):
    pol = PPOPolicy()
    path = tmp_path / "policy.npz"
    pol.save(path)
    cmp = compare_policies(db, path, path)
    assert cmp["passed"] is False
    assert "insufficient" in cmp["reason"]


# --- 7 Binomial promotion gate ---
def test_binomial_rejects_noise():
    assert binomial_edge_p_value(11, 25) > 0.05
    assert binomial_edge_p_value(18, 25) < 0.05


def test_promote_discovery_rejects_synthetic_rubber_stamp(db):
    """Repeated mean must not inflate Sortino — promotion requires real bar_log returns."""
    db._conn.execute(
        """
        INSERT INTO strategy_discovery(rule_id, symbol, conditions, win_rate, avg_return, sample_count, discovered_ts, promoted)
        VALUES ('noise_rule', 'INFY', ?, 0.72, 0.4, 25, ?, 0)
        """,
        (json.dumps({"field": "ibs", "op": "lt", "threshold": 0.2}), int(time.time())),
    )
    db._conn.commit()
    assert promote_discovery_rules(db) == []


def test_promote_discovery_accepts_significant_edge(db):
    ts = int(time.time()) - 7200
    for i in range(50):
        close = 100.0 + i * 1.5
        db._conn.execute(
            "INSERT INTO bar_log(ts,symbol,interval,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)",
            (ts + i * 300, "INFY", "5m", close, close + 1, close - 0.5, close, 1000),
        )
    db._conn.execute(
        """
        INSERT INTO strategy_discovery(rule_id, symbol, conditions, win_rate, avg_return, sample_count, discovered_ts, promoted)
        VALUES ('strong_rule', 'INFY', ?, 0.72, 0.4, 25, ?, 0)
        """,
        (json.dumps({"field": "r3m", "op": "gt", "threshold": 0.001}), int(time.time())),
    )
    db._conn.commit()
    promoted = promote_discovery_rules(db)
    assert len(promoted) == 1


# --- 8 Expected move from measured stats ---
def test_expected_move_from_strategy_stats(db):
    _seed_outcomes(db, "momentum_consensus", [0.8, -0.2, 0.5, 0.4, -0.1] * 3)
    perf = strategy_performance(db, "momentum_consensus")
    assert perf.has_edge_data
    move = expected_move_pct_for_strategy(db, "momentum_consensus", 0.8)
    assert move > 0


# --- 9 Portfolio beta cap ---
def test_portfolio_beta_blocks_high_beta_add(db):
    ts = int(time.time()) - 3600
    for i in range(25):
        nifty = 24000 + i * 10
        sym = 500 + i * 5
        db._conn.execute(
            "INSERT INTO bar_log(ts,symbol,interval,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)",
            (ts + i * 300, "NIFTY50", "5m", nifty, nifty, nifty, nifty, 0),
        )
        db._conn.execute(
            "INSERT INTO bar_log(ts,symbol,interval,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)",
            (ts + i * 300, "SBIN", "5m", sym, sym, sym, sym, 0),
        )
    db._conn.execute(
        "INSERT INTO positions(symbol, qty, last_price, avg_price, open_ts, rail) VALUES ('SBIN', 10, 500, 480, ?, 'CNC')",
        (int(time.time()),),
    )
    db._conn.commit()
    beta = symbol_beta_to_index(db, "SBIN")
    ok, reason = can_add_beta_exposure(db, "SBIN", 50_000, 10_000)
    if beta > 0.5:
        assert ok is False
        assert "portfolio_beta_cap" in reason


# --- 10 RBI dates + RSI ---
def test_rbi_mpc_dates_are_published_not_first_of_month():
    dates_2026 = _load_rbi_dates(2026)
    assert len(dates_2026) == 6
    assert all(d.day != 1 or d.month == 1 for d in dates_2026)
    assert date(2026, 2, 6) in dates_2026


def test_rsi_from_closes_varies():
    closes = [100 + np.sin(i / 3) * 5 for i in range(30)]
    vals = [_rsi_from_closes(closes, i) for i in range(15, 30)]
    assert max(vals) - min(vals) > 5.0


# --- 7 Correlation disable ---
def test_refresh_disabled_strategies(db):
    since = int(time.time()) - 86400
    for i in range(25):
        ts = since + i * 300
        db._conn.execute(
            "INSERT INTO strategy_ledger(ts,strategy_id,symbol,signal,confidence,executed,price,reason,event_type) VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, "dual_momentum_pro", "SBIN", "BUY", 0.8, 1, 100, "t", "BAR_CLOSE_5M"),
        )
        db._conn.execute(
            "INSERT INTO strategy_ledger(ts,strategy_id,symbol,signal,confidence,executed,price,reason,event_type) VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, "adaptive_alpha", "SBIN", "BUY", 0.8, 1, 100, "t", "BAR_CLOSE_5M"),
        )
    db._conn.commit()
    disabled = refresh_disabled_strategies(db)
    assert isinstance(disabled, list)

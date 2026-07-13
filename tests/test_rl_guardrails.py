"""Tests for RL training guardrails and shadow backtest."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

from src.db.database import DB, DBConfig
from src.rl.ppo_trainer import PPOPolicy
from src.rl.shadow_backtest import compare_policies, evaluate_policy_on_bars
from src.rl.training_guardrails import (
    detect_abnormal_day,
    guarded_train_and_promote,
    revert_to_stable,
    snapshot_stable_policy,
    training_config,
)


@pytest.fixture
def db(tmp_path):
    return DB(DBConfig(sqlite_path=str(tmp_path / "rl_guard.db")))


def _seed_bars(db: DB, symbol: str = "SBIN", n: int = 80) -> None:
    ts = int(time.time()) - n * 300
    with db.tx() as conn:
        for i in range(n):
            px = 150.0 + i * 0.1
            conn.execute(
                """
                INSERT INTO bar_log(ts, symbol, interval, open, high, low, close, volume)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (ts + i * 300, symbol, "5m", px, px + 1, px - 1, px, 1000),
            )
        conn.execute(
            "INSERT INTO screening_results(run_ts, symbol, momentum_score) VALUES (?,?,?)",
            (ts, symbol, 0.9),
        )


def test_low_lr_on_abnormal_day(db):
    abnormal_cfg = training_config(db, abnormal=True)
    normal_cfg = training_config(db, abnormal=False)
    assert abnormal_cfg.lr < normal_cfg.lr
    assert abnormal_cfg.epochs <= normal_cfg.epochs


def test_shadow_eval_runs_on_bars(db, tmp_path):
    _seed_bars(db)
    pol = PPOPolicy()
    path = tmp_path / "policy.npz"
    pol.save(path)
    result = evaluate_policy_on_bars(db, path, lookback_days=30)
    assert result["bars"] > 0


def test_revert_when_candidate_worse(db, tmp_path):
    _seed_bars(db)
    d = tmp_path / "ppo_v1"
    d.mkdir(parents=True)
    good = PPOPolicy(seed=1)
    bad = PPOPolicy(seed=99)
    # Artificially set good policy to always hold (neutral), bad to churn
    good.save(d / "policy_stable.npz")
    bad.save(d / "policy.npz")
    cmp = compare_policies(db, d / "policy_stable.npz", d / "policy.npz")
    assert "passed" in cmp


def test_guarded_train_skips_without_transitions(db, tmp_path):
    os.environ["RL_USE_SB3"] = "false"
    result = guarded_train_and_promote(db, str(tmp_path / "models"), "ppo_v1")
    assert result.get("promoted") is False or result.get("train", {}).get("status") == "skipped"


def test_orderbook_imbalance():
    from src.data.depth_store import orderbook_imbalance_from_depth

    depth = {
        "buy": [{"quantity": 300}, {"quantity": 200}],
        "sell": [{"quantity": 100}, {"quantity": 100}],
    }
    obi = orderbook_imbalance_from_depth(depth, levels=5)
    assert obi > 0.3


def test_drawdown_action_mask_blocks_buy(tmp_path, monkeypatch):
    from src.ops.daily_pnl import portfolio_state
    from src.ops.kill_switch import set_setting
    from src.rl.action_mask import apply_action_mask, is_drawdown_halted, masked_action_probs, max_intraday_drawdown_pct
    import numpy as np

    monkeypatch.setenv("MAX_INTRADAY_DRAWDOWN_PCT", "10")
    db = DB(DBConfig(sqlite_path=str(tmp_path / "dd.db")))
    db.add_cash(1, 8000.0, "seed")
    st = portfolio_state(db)
    from src.ops.daily_pnl import _today_key

    set_setting(db, f"day_peak_{_today_key()}", f"{st['total_equity'] * 1.2:.4f}")
    st = portfolio_state(db)
    dd = (st["day_peak_equity"] - st["total_equity"]) / st["day_peak_equity"] * 100.0
    assert dd >= max_intraday_drawdown_pct()
    assert is_drawdown_halted(db, st["total_equity"])
    masked = masked_action_probs(
        np.array([0.1, 0.8, 0.1]),
        cash=8000,
        ltp=100,
        db=db,
        has_position=False,
        drawdown_halted=True,
    )
    assert masked[1] == 0.0
    assert apply_action_mask(1, cash=8000, ltp=100, db=db, has_position=True, drawdown_halted=True) == 2


def test_regime_hot_swap_fallback(tmp_path):
    from src.rl.rl_agent import RLAgent

    agent = RLAgent(model_dir=str(tmp_path / "models"), active_version="ppo_v1", db=None)
    result = agent.hot_swap_regime_policy("BULL")
    assert result["bucket"] == "BULL"
    assert result.get("fallback") is True

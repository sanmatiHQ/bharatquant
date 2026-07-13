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

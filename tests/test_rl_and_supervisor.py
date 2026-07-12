"""Tests for PPO trainer, market supervisor, state encoder."""
from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.db.database import DB, DBConfig
from src.ops.market_supervisor import evaluate_market_activity
from src.rl.ppo_trainer import PPOConfig, PPOPolicy, train_ppo
from src.rl.rl_buffer import RLBuffer
from src.rl.state_encoder import STATE_DIM, encode_state, index_action


@pytest.fixture
def db(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "t.db")
    return DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))


def test_encode_state_dim():
    class Ctx:
        regime = "RISK_ON"
        fii_net_cr = 1000
        gift_nifty_change_pct = 0.5
        india_vix = 15
        positions = {"A": 1}

    v = encode_state(Ctx(), symbol="INFY", confidence=0.8, score=0.7)
    assert len(v) == STATE_DIM


def test_ppo_policy_save_load(tmp_path):
    p = PPOPolicy()
    path = tmp_path / "policy.npz"
    p.save(path)
    p2 = PPOPolicy.load(path)
    assert p2.W.shape == p.W.shape


def test_train_ppo_skips_without_data(db):
    r = train_ppo(db, str(db.path.parent / "models"), version="ppo_v1", cfg=PPOConfig(epochs=1))
    assert r["status"] == "skipped"


def test_train_ppo_with_transitions(db):
    buf = RLBuffer(db)
    for i in range(12):
        s = {str(j): 0.1 * j for j in range(STATE_DIM)}
        buf.push("ppo_v1", "INFY", s, "buy", 0.01, s, False)
    model_dir = str(db.path.parent / "models")
    r = train_ppo(db, model_dir, version="ppo_v1", cfg=PPOConfig(epochs=2))
    assert r["status"] == "ok"
    assert os.path.exists(r["path"])


def test_evaluate_market_preopen(db):
    with patch("src.ops.market_supervisor._is_weekday", return_value=True):
        with patch.dict(os.environ, {"PAPER_ALWAYS_ON": "false", "TRADING_MODE": "paper"}):
            run, reason = evaluate_market_activity(db, "Pre-Open")
    assert run is True
    assert "pre" in reason


def test_evaluate_market_weekend(db):
    with patch("src.ops.market_supervisor._is_weekday", return_value=False):
        with patch.dict(os.environ, {"PAPER_ALWAYS_ON": "false", "TRADING_MODE": "paper"}):
            run, reason = evaluate_market_activity(db, "Close")
    assert run is False


def test_action_index_roundtrip():
    assert index_action(1) == "buy"

"""Tests for hybrid LLM+RL stack and safety modules."""
from __future__ import annotations

import os
import time

import numpy as np
import pytest

from src.db.database import DB, DBConfig
from src.ops.execution_cooldown import can_place_order, mark_order_placed
from src.ops.budget_gate import remaining_budget
from src.rl.action_mask import is_buy_allowed, masked_action_probs
from src.rl.reward import compute_reward, reward_config_from_env
from src.rl.state_encoder import STATE_DIM, encode_state_from_dict
from src.strategies.base import MarketContext
from src.ingest.llm_macro import compute_llm_bias


def test_state_vector_dim_16():
    vec = encode_state_from_dict({"regime": "RISK_ON", "llm_bias": 0.5})
    assert len(vec) == STATE_DIM == 16


def test_action_mask_blocks_expensive_buy():
    probs = np.array([0.1, 0.8, 0.1])
    masked = masked_action_probs(probs, cash=1000, ltp=2500, db=None, has_position=False)
    assert masked[1] == 0.0
    assert masked[0] > 0.9


def test_time_decay_reward():
    cfg = reward_config_from_env()
    r_stagnant = compute_reward(0.0, 0.0, cfg, hold_minutes=60, unrealized_pnl_pct=-1.0)
    r_fresh = compute_reward(0.0, 0.0, cfg, hold_minutes=0)
    assert r_stagnant < r_fresh


def test_execution_cooldown(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "cd.db")))
    ok, _ = can_place_order(db)
    assert ok is True
    mark_order_placed(db)
    ok2, wait = can_place_order(db)
    assert ok2 is False
    assert wait > 0


@pytest.mark.asyncio
async def test_llm_failure_defaults_zero(tmp_path):
    os.environ["LLM_ENABLED"] = "false"
    db = DB(DBConfig(sqlite_path=str(tmp_path / "llm.db")))
    bias = await compute_llm_bias(db, {"fii_net_cr": 100})
    assert bias == 0.0


def test_market_context_llm_bias_field():
    ctx = MarketContext(llm_bias=0.7, futures_oi_chg=1.5)
    assert ctx.llm_bias == 0.7
    assert ctx.futures_oi_chg == 1.5


def test_gym_env_daily_budget_mask():
    pytest.importorskip("gymnasium")
    from src.rl.gym_env import NSETradingEnv

    env = NSETradingEnv(np.linspace(100, 110, 100), daily_budget=2000)
    obs, _ = env.reset()
    assert obs.shape == (STATE_DIM,)
    obs, r, term, trunc, info = env.step(1)
    assert info["qty"] in (0, 1)

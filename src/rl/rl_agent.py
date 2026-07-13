"""
Versioned RL agent — PPO policy with action masking.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

from .ppo_trainer import PPOPolicy
from .state_encoder import STATE_DIM, encode_state, index_action
from .action_mask import masked_action_probs, is_buy_allowed

logger = logging.getLogger("bharatquant.rl_agent")


class RLAgent:
    def __init__(self, model_dir: str | None = None, active_version: str | None = None, db=None) -> None:
        self.model_dir = model_dir or os.getenv("RL_MODEL_DIR", "models/rl")
        self.active_version = active_version or os.getenv("RL_ACTIVE_VERSION", "ppo_v1")
        self.db = db
        self._policy: PPOPolicy | None = None
        self._load_policy()

    def _load_policy(self) -> None:
        path = Path(self.model_dir) / self.active_version / "policy.npz"
        if path.exists():
            self._policy = PPOPolicy.load(path)
            logger.info("rl_policy_loaded", extra={"path": str(path)})
        else:
            self._policy = None

    def reload(self) -> None:
        self._load_policy()

    def is_learning_enabled(self) -> bool:
        return self._policy is not None and self.active_version != "baseline"

    def transition_count(self) -> int:
        if not self.db:
            return 0
        row = self.db._conn.execute("SELECT COUNT(*) AS c FROM rl_transitions").fetchone()
        return int(row["c"]) if row else 0

    def act(
        self,
        state: dict,
        symbol: str = "",
        *,
        ltp: float = 0.0,
        cash: float = 0.0,
        has_position: bool = False,
    ) -> str:
        if self.active_version == "baseline" or self._policy is None:
            score = float(state.get("score", state.get("0", 0.0)))
            return "buy" if score > 0.55 else "hold"
        vec = _state_vector(state)
        a, _ = self._policy.act(vec)
        probs = self._policy.act_probs(vec)
        if ltp > 0:
            masked = masked_action_probs(
                probs if isinstance(probs, np.ndarray) else np.array([0.33, 0.33, 0.34]),
                cash=cash,
                ltp=ltp,
                db=self.db,
                has_position=has_position,
            )
            a = int(np.argmax(masked))
        return index_action(a)

    def primary_ready(self) -> bool:
        min_n = int(os.getenv("RL_PRIMARY_MIN_TRANSITIONS", "200"))
        return self.is_learning_enabled() and self.transition_count() >= min_n


def _state_vector(state: dict) -> np.ndarray:
    if all(str(i) in state for i in range(STATE_DIM)):
        return np.array([float(state[str(i)]) for i in range(STATE_DIM)], dtype=np.float64)
    vec = encode_state(_CtxStub(state), score=float(state.get("score", 0)))
    if len(vec) < STATE_DIM:
        vec = vec + [0.0] * (STATE_DIM - len(vec))
    return np.array(vec[:STATE_DIM], dtype=np.float64)


class _CtxStub:
    def __init__(self, d: dict) -> None:
        self.regime = d.get("regime", "NEUTRAL")
        self.fii_net_cr = float(d.get("fii", 0)) * 5000
        self.gift_nifty_change_pct = float(d.get("gift", 0)) * 5
        self.india_vix = float(d.get("vix", 0)) * 30
        self.llm_bias = float(d.get("llm_bias", 0))
        self.futures_oi_chg = float(d.get("futures_oi_chg", 0))
        self.us_vix_chg = float(d.get("us_vix_chg", 0))
        self.nikkei_chg = float(d.get("nikkei_chg", 0))
        self.hang_seng_chg = float(d.get("hang_seng_chg", 0))
        self.spread_bps = {}
        self.positions = {}

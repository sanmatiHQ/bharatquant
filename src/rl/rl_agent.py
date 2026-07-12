"""
Versioned RL agent — loads PPO policy from models/rl/{version}/policy.npz
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .ppo_trainer import PPOPolicy
from .state_encoder import STATE_DIM, encode_state, index_action

logger = logging.getLogger("bharatquant.rl_agent")


class RLAgent:
    def __init__(self, model_dir: str | None = None, active_version: str | None = None) -> None:
        self.model_dir = model_dir or os.getenv("RL_MODEL_DIR", "models/rl")
        self.active_version = active_version or os.getenv("RL_ACTIVE_VERSION", "ppo_v1")
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

    def act(self, state: dict, symbol: str = "") -> str:
        if self.active_version == "baseline" or self._policy is None:
            score = float(state.get("score", state.get("0", 0.0)))
            return "buy" if score > 0.55 else "hold"
        vec = _state_vector(state)
        a, _ = self._policy.act(vec)
        return index_action(a)


def _state_vector(state: dict) -> "np.ndarray":
    import numpy as np

    if all(str(i) in state for i in range(STATE_DIM)):
        return np.array([float(state[str(i)]) for i in range(STATE_DIM)])
    return np.array(encode_state(_CtxStub(state), score=float(state.get("score", 0))), dtype=np.float64)


class _CtxStub:
    def __init__(self, d: dict) -> None:
        self.regime = d.get("regime", "NEUTRAL")
        self.fii_net_cr = float(d.get("fii", 0)) * 5000
        self.gift_nifty_change_pct = float(d.get("gift", 0)) * 5
        self.india_vix = float(d.get("vix", 0)) * 30
        self.positions = {}

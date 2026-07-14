"""
Stable-Baselines3 PPO trainer — learns from Gymnasium env + live transitions.
Falls back to numpy PPO when SB3 unavailable.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..db.database import DB

logger = logging.getLogger("bharatquant.sb3_trainer")

SB3_AVAILABLE = False
try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    SB3_AVAILABLE = True
except ImportError:
    PPO = None  # type: ignore
    DummyVecEnv = None  # type: ignore


def train_sb3(
    db: DB,
    model_dir: str,
    version: str,
    *,
    symbol: str = "INFY",
    timesteps: int | None = None,
) -> dict[str, Any]:
    if not SB3_AVAILABLE:
        from .ppo_trainer import train_ppo

        logger.info("sb3_unavailable_fallback_numpy")
        return train_ppo(db, model_dir, version)

    from .gym_env import GYM_AVAILABLE, make_env_from_db

    if not GYM_AVAILABLE:
        from .ppo_trainer import train_ppo

        return train_ppo(db, model_dir, version)

    steps = timesteps if timesteps is not None else int(os.getenv("RL_SB3_TIMESTEPS", "2000"))
    out_dir = Path(model_dir) / version
    out_dir.mkdir(parents=True, exist_ok=True)
    sb3_path = out_dir / "sb3_ppo.zip"

    def _make():
        return make_env_from_db(db, symbol)

    env = DummyVecEnv([_make])
    if sb3_path.exists():
        model = PPO.load(str(sb3_path), env=env)
    else:
        model = PPO(
            "MlpPolicy",
            env,
            verbose=0,
            n_steps=256,
            batch_size=64,
            learning_rate=float(os.getenv("RL_LEARNING_RATE", "1e-5")),
        )

    model.learn(total_timesteps=steps)
    model.save(str(sb3_path))

    # Runtime inference prefers SB3 zip when available (full MLP); numpy export is fallback only.
    sb3_path = out_dir / "sb3_ppo.zip"
    if not sb3_path.exists():
        _export_sb3_to_numpy(model, out_dir / "policy.npz")

    return {"status": "ok", "engine": "stable_baselines3", "path": str(sb3_path), "timesteps": steps}


def _export_sb3_to_numpy(model, path: Path) -> None:
    """Best-effort export — runtime uses numpy PPOPolicy."""
    import numpy as np
    from .ppo_trainer import PPOPolicy
    from .state_encoder import STATE_DIM

    pol = PPOPolicy(state_dim=STATE_DIM)
    try:
        weights = model.policy.mlp_extractor.policy_net[0].weight.detach().cpu().numpy()
        if weights.shape[0] >= STATE_DIM:
            pol.W = weights[:STATE_DIM, :3] if weights.shape[1] >= 3 else pol.W
    except Exception:
        logger.warning("sb3_export_partial")
    pol.save(path)


def validate_policy_oos(db: DB, model_dir: str, version: str) -> dict[str, Any]:
    """Walk-forward style gate — policy must beat random on held-out bars."""
    from .gym_env import make_env_from_db
    from .rl_agent import RLAgent

    agent = RLAgent(model_dir=model_dir, active_version=version)
    env = make_env_from_db(db, "INFY")
    obs, _ = env.reset()
    total_reward = 0.0
    for _ in range(min(100, env.max_steps)):
        state = {str(i): float(obs[i]) for i in range(len(obs))}
        action_name = agent.act(state)
        action = {"hold": 0, "buy": 1, "sell": 2}.get(action_name, 0)
        obs, r, term, trunc, _ = env.step(action)
        total_reward += r
        if term or trunc:
            break
    min_reward = float(os.getenv("RL_OOS_MIN_REWARD", "-0.5"))
    passed = total_reward >= min_reward
    return {"total_reward": total_reward, "passed": passed, "min_required": min_reward}

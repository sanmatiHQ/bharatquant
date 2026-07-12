"""
Lightweight PPO policy trainer (numpy) — learns from rl_transitions in SQLite.

Actions: hold=0, buy=1, sell=2
Saves: {model_dir}/{version}/policy.npz
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np

from .state_encoder import STATE_DIM, action_index, index_action
from ..db.database import DB, DBConfig

logger = logging.getLogger("bharatquant.ppo")


@dataclass
class PPOConfig:
    lr: float = 3e-4
    gamma: float = 0.99
    clip_eps: float = 0.2
    epochs: int = 4
    batch_size: int = 64


class PPOPolicy:
    """Softmax linear policy + value head."""

    def __init__(self, state_dim: int = STATE_DIM, n_actions: int = 3, seed: int = 42) -> None:
        rng = np.random.default_rng(seed)
        self.W = rng.normal(0, 0.1, (state_dim, n_actions))
        self.b = np.zeros(n_actions)
        self.Vw = rng.normal(0, 0.1, state_dim)
        self.Vb = 0.0

    def probs(self, state: np.ndarray) -> np.ndarray:
        logits = state @ self.W + self.b
        logits -= logits.max()
        e = np.exp(logits)
        return e / e.sum()

    def value(self, state: np.ndarray) -> float:
        return float(state @ self.Vw + self.Vb)

    def act(self, state: np.ndarray) -> Tuple[int, float]:
        p = self.probs(state)
        a = int(np.argmax(p))
        return a, float(p[a])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, W=self.W, b=self.b, Vw=self.Vw, Vb=self.Vb)

    @classmethod
    def load(cls, path: Path) -> "PPOPolicy":
        data = np.load(path)
        pol = cls()
        pol.W = data["W"]
        pol.b = data["b"]
        pol.Vw = data["Vw"]
        pol.Vb = float(data["Vb"])
        return pol


def _load_transitions(db: DB, version: str, limit: int = 5000) -> List[dict]:
    cur = db._conn.execute(
        """
        SELECT state, action, reward, next_state, done
        FROM rl_transitions WHERE version=? ORDER BY ts DESC LIMIT ?
        """,
        (version, limit),
    )
    rows = []
    for r in cur.fetchall():
        try:
            state = json.loads(r["state"].decode() if isinstance(r["state"], bytes) else r["state"])
            nxt = json.loads(r["next_state"].decode() if isinstance(r["next_state"], bytes) else r["next_state"])
            if isinstance(state, dict):
                state = list(state.values())[:STATE_DIM]
            if isinstance(nxt, dict):
                nxt = list(nxt.values())[:STATE_DIM]
            rows.append({
                "state": np.array(state, dtype=np.float64),
                "action": action_index(str(r["action"])),
                "reward": float(r["reward"]),
                "next_state": np.array(nxt, dtype=np.float64),
                "done": bool(r["done"]),
            })
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return rows


def train_ppo(
    db: DB,
    model_dir: str,
    version: str = "ppo_v1",
    cfg: PPOConfig | None = None,
) -> dict:
    cfg = cfg or PPOConfig()
    rows = _load_transitions(db, version)
    if len(rows) < 8:
        return {"status": "skipped", "reason": f"need >=8 transitions, have {len(rows)}"}

    policy_path = Path(model_dir) / version / "policy.npz"
    policy = PPOPolicy.load(policy_path) if policy_path.exists() else PPOPolicy()

    states = np.stack([r["state"] for r in rows])
    actions = np.array([r["action"] for r in rows])
    rewards = np.array([r["reward"] for r in rows])
    next_states = np.stack([r["next_state"] for r in rows])
    dones = np.array([r["done"] for r in rows])

    # Returns-to-go
    returns = np.zeros_like(rewards)
    g = 0.0
    for i in reversed(range(len(rewards))):
        g = rewards[i] + cfg.gamma * g * (1.0 - dones[i])
        returns[i] = g

    adv = returns - np.array([policy.value(s) for s in states])
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)

    for _ in range(cfg.epochs):
        for i in range(len(rows)):
            s = states[i]
            a = actions[i]
            old_p = policy.probs(s)[a]
            adv_i = adv[i]
            ret_i = returns[i]

            # PPO clipped surrogate (single-step policy gradient)
            logits = s @ policy.W + policy.b
            logits -= logits.max()
            probs = np.exp(logits) / np.exp(logits).sum()
            new_p = probs[a]
            ratio = new_p / max(old_p, 1e-8)
            clipped = np.clip(ratio, 1 - cfg.clip_eps, 1 + cfg.clip_eps)
            loss_pg = -min(ratio * adv_i, clipped * adv_i)

            # Value + policy gradients (manual)
            for j in range(probs.shape[0]):
                grad = probs[j] * (1 if j == a else 0) - probs[j] * probs[a]
                policy.W[:, j] -= cfg.lr * loss_pg * grad * s
                policy.b[j] -= cfg.lr * loss_pg * grad
            v_err = policy.value(s) - ret_i
            policy.Vw -= cfg.lr * v_err * s
            policy.Vb -= cfg.lr * v_err

    policy.save(policy_path)
    logger.info("ppo_trained", extra={"version": version, "transitions": len(rows), "path": str(policy_path)})
    return {"status": "ok", "transitions": len(rows), "path": str(policy_path)}

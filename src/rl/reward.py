"""
Reward computation for RL — profit, drawdown, time-decay on stagnant holds.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class RewardConfig:
    drawdown_penalty: float
    hold_decay_per_min: float
    loss_hold_penalty: float


def reward_config_from_env() -> RewardConfig:
    return RewardConfig(
        drawdown_penalty=float(os.getenv("RL_DRAWDOWN_PENALTY", "0.5")),
        hold_decay_per_min=float(os.getenv("RL_HOLD_DECAY_PER_MIN", "0.00015")),
        loss_hold_penalty=float(os.getenv("RL_LOSS_HOLD_PENALTY", "0.002")),
    )


def compute_reward(
    after_cost_daily_return: float,
    drawdown: float,
    cfg: RewardConfig,
    *,
    hold_minutes: float = 0.0,
    unrealized_pnl_pct: float = 0.0,
) -> float:
    """Reward = return - drawdown penalty - time decay - loss-hold penalty."""
    base = float(after_cost_daily_return - cfg.drawdown_penalty * drawdown)
    if hold_minutes > 5:
        base -= cfg.hold_decay_per_min * hold_minutes
    if unrealized_pnl_pct < -0.5 and hold_minutes > 15:
        base -= cfg.loss_hold_penalty * (hold_minutes / 60.0)
    return float(base)


def compute_trade_reward(realized_pnl: float, cost_basis: float, cfg: RewardConfig) -> float:
    if cost_basis <= 0:
        return 0.0
    ret = realized_pnl / cost_basis
    penalty = cfg.drawdown_penalty * max(0.0, -ret)
    bonus = 0.05 * max(0.0, ret) if ret > 0.01 else 0.0
    return float(ret - penalty + bonus)


def compute_skip_reward(reason: str, cfg: RewardConfig) -> float:
    if reason in ("budget_exceeded_pending_approval", "daily_budget_cap", "kill_switch"):
        return -0.002
    return -0.001

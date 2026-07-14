"""
Reward computation for RL — Sortino-shaped: net return minus downside deviation penalty.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..risk.risk_metrics import downside_deviation


@dataclass
class RewardConfig:
    sortino_lambda: float
    hold_decay_per_min: float
    loss_hold_penalty: float
    drawdown_penalty: float  # catastrophic circuit only — secondary to downside dev


def reward_config_from_env() -> RewardConfig:
    return RewardConfig(
        sortino_lambda=float(os.getenv("RL_SORTINO_LAMBDA", "0.35")),
        hold_decay_per_min=float(os.getenv("RL_HOLD_DECAY_PER_MIN", "0.00015")),
        loss_hold_penalty=float(os.getenv("RL_LOSS_HOLD_PENALTY", "0.002")),
        drawdown_penalty=float(os.getenv("RL_DRAWDOWN_PENALTY", "0.15")),
    )


def compute_reward(
    after_cost_daily_return: float,
    drawdown: float,
    cfg: RewardConfig,
    *,
    hold_minutes: float = 0.0,
    unrealized_pnl_pct: float = 0.0,
    recent_returns: list[float] | None = None,
) -> float:
    """
    Sortino-shaped reward: net return - λ·downside_deviation - hold decay.
    Downside deviation penalizes bad volatility only, not upside variance.
    """
    base = float(after_cost_daily_return)
    if recent_returns and len(recent_returns) >= 3:
        dd_dev = downside_deviation(recent_returns)
        base -= cfg.sortino_lambda * dd_dev
    if drawdown > 0.05:
        base -= cfg.drawdown_penalty * drawdown
    if hold_minutes > 5:
        base -= cfg.hold_decay_per_min * hold_minutes
    if unrealized_pnl_pct < -0.5 and hold_minutes > 15:
        base -= cfg.loss_hold_penalty * (hold_minutes / 60.0)
    return float(base)


def compute_trade_reward(
    realized_pnl: float,
    cost_basis: float,
    cfg: RewardConfig,
    *,
    recent_returns: list[float] | None = None,
) -> float:
    if cost_basis <= 0:
        return 0.0
    ret = realized_pnl / cost_basis
    penalty = 0.0
    if recent_returns and len(recent_returns) >= 3:
        penalty = cfg.sortino_lambda * downside_deviation(recent_returns + [ret])
    elif ret < 0:
        penalty = cfg.sortino_lambda * abs(ret) * 0.5
    return float(ret - penalty)


def compute_skip_reward(reason: str, cfg: RewardConfig) -> float:
    if reason in ("budget_exceeded_pending_approval", "daily_budget_cap", "kill_switch"):
        return -0.002
    return -0.001

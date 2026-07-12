"""
Reward computation for RL observer mode.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RewardConfig:
    drawdown_penalty: float


def compute_reward(after_cost_daily_return: float, drawdown: float, cfg: RewardConfig) -> float:
    """Reward = daily return - penalty * drawdown."""
    return float(after_cost_daily_return - cfg.drawdown_penalty * drawdown)


def compute_trade_reward(realized_pnl: float, cost_basis: float, cfg: RewardConfig) -> float:
    """Per-trade reward from realized PnL vs entry notional."""
    if cost_basis <= 0:
        return 0.0
    ret = realized_pnl / cost_basis
    penalty = cfg.drawdown_penalty * max(0.0, -ret)
    return float(ret - penalty)

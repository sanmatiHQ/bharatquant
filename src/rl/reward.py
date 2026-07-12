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

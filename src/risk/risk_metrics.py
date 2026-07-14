"""Risk-adjusted fitness metrics — Sortino, Calmar, downside deviation (shared learning objective)."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskFitness:
    sortino: float
    calmar: float
    downside_dev: float
    max_drawdown: float
    mean_return: float
    n: int

    @property
    def composite(self) -> float:
        """Primary promotion/fitness score — risk-adjusted, not raw PnL."""
        if self.n < 3:
            return 0.0
        s = max(-5.0, min(5.0, self.sortino))
        c = max(-5.0, min(5.0, self.calmar))
        return 0.55 * s + 0.45 * c


def downside_deviation(returns: list[float], target: float = 0.0) -> float:
    """Sortino denominator — penalizes only returns below target."""
    if len(returns) < 2:
        return 0.0
    downs = [min(0.0, r - target) ** 2 for r in returns]
    if not any(d > 0 for d in downs):
        return 0.0
    return math.sqrt(sum(downs) / len(returns))


def sortino_ratio(returns: list[float], target: float = 0.0) -> float:
    if len(returns) < 3:
        return 0.0
    mean_r = sum(returns) / len(returns)
    dd = downside_deviation(returns, target)
    if dd <= 1e-12:
        return mean_r * 10.0 if mean_r > 0 else 0.0
    return mean_r / dd


def max_drawdown_from_returns(returns: list[float]) -> float:
    """Peak-to-trough drawdown on compounded equity curve."""
    if not returns:
        return 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd


def calmar_ratio(returns: list[float]) -> float:
    if len(returns) < 5:
        return 0.0
    total = sum(returns)
    mdd = max_drawdown_from_returns(returns)
    if mdd <= 1e-6:
        return total * 5.0 if total > 0 else 0.0
    return total / mdd


def fitness_from_returns(returns: list[float]) -> RiskFitness:
    if not returns:
        return RiskFitness(0.0, 0.0, 0.0, 0.0, 0.0, 0)
    return RiskFitness(
        sortino=sortino_ratio(returns),
        calmar=calmar_ratio(returns),
        downside_dev=downside_deviation(returns),
        max_drawdown=max_drawdown_from_returns(returns),
        mean_return=sum(returns) / len(returns),
        n=len(returns),
    )

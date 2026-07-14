"""Risk-adjusted fitness metrics — Sortino, Calmar, downside deviation (shared learning objective)."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

# Sampling-frequency annualization — callers MUST pass the value matching their return series.
# 252 trading days × 75 five-minute bars per session (6.25h × 12 bars/h)
PERIODS_PER_YEAR_5M_BAR = 18_900
# Irregular per-signal / per-trade outcomes (~2 labeled signals per trading day)
PERIODS_PER_YEAR_SIGNAL = int(os.getenv("SIGNAL_TRADES_PER_YEAR", "504"))
_MIN_TRUST_SAMPLES = int(os.getenv("RISK_MIN_TRUST_SAMPLES", "20"))


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


def periods_per_year_discovery(n: int, lookback_days: int = 14) -> float:
    """Extrapolate discovery hit frequency to annual periods for Calmar annualization."""
    if n <= 0 or lookback_days <= 0:
        return float(PERIODS_PER_YEAR_SIGNAL)
    trading_days = max(1.0, lookback_days * (5.0 / 7.0))
    return max(float(n), (n / trading_days) * 252.0)


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
    n = len(returns)
    mean_r = sum(returns) / n
    dd = downside_deviation(returns, target)
    if dd <= 1e-12:
        # Near-zero variance: only trust with a large sample; else proxy-artifact → 0
        if mean_r <= 0 or n < _MIN_TRUST_SAMPLES:
            return 0.0
        return min(3.0, abs(mean_r) * math.sqrt(n))
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


def calmar_ratio(returns: list[float], periods_per_year: int | float = 252) -> float:
    """
    Calmar = annualized compound return / max drawdown.
    `returns` are per-period fractional returns (e.g. 0.01 = 1%).
    `periods_per_year` must match the sampling frequency of the series.
    """
    if len(returns) < 5:
        return 0.0
    n = len(returns)
    equity = 1.0
    for r in returns:
        equity *= 1.0 + r
    if equity <= 0:
        return -5.0
    annualized_return = equity ** (float(periods_per_year) / n) - 1.0
    mdd = max_drawdown_from_returns(returns)
    if mdd <= 1e-6:
        if annualized_return > 0 and n >= _MIN_TRUST_SAMPLES:
            return min(5.0, annualized_return * 5.0)
        return 0.0
    return annualized_return / mdd


def cumulative_return_drawdown_ratio(returns: list[float]) -> float:
    """Raw cumulative return / max DD — not annualized; fixed-window ranking only."""
    if len(returns) < 5:
        return 0.0
    mdd = max_drawdown_from_returns(returns)
    if mdd <= 1e-6:
        return 0.0
    return sum(returns) / mdd


def fitness_from_returns(
    returns: list[float],
    *,
    periods_per_year: float | int,
) -> RiskFitness:
    if not returns:
        return RiskFitness(0.0, 0.0, 0.0, 0.0, 0.0, 0)
    ppy = float(periods_per_year)
    return RiskFitness(
        sortino=sortino_ratio(returns),
        calmar=calmar_ratio(returns, periods_per_year=ppy),
        downside_dev=downside_deviation(returns),
        max_drawdown=max_drawdown_from_returns(returns),
        mean_return=sum(returns) / len(returns),
        n=len(returns),
    )

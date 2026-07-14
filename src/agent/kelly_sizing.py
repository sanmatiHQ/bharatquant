"""Fractional Kelly — adaptive fraction shrinks when win-rate estimate is noisy."""
from __future__ import annotations

import os

from .strategy_stats import win_rate_variance


def kelly_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fraction: float | None = None,
    *,
    wr_variance: float | None = None,
) -> float:
    if avg_loss <= 0 or win_rate <= 0:
        return 0.0
    base_frac = fraction if fraction is not None else float(os.getenv("KELLY_BASE_FRACTION", "0.25"))
    b = avg_win / avg_loss
    q = 1 - win_rate
    kelly = (win_rate * b - q) / b if b else 0.0
    kelly = max(0.0, min(kelly, 1.0))
    adaptive = base_frac
    if wr_variance is not None:
        cap = float(os.getenv("KELLY_WR_VAR_CAP", "0.04"))
        shrink = float(os.getenv("KELLY_NOISE_SHRINK", "0.75"))
        noise = min(1.0, wr_variance / max(cap, 1e-6))
        adaptive = base_frac * max(0.05, 1.0 - shrink * noise)
    return kelly * adaptive


def rupees_from_kelly(
    equity: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    max_rupees: float | None = None,
    *,
    safety_scalar: float | None = None,
    wr_variance: float | None = None,
    lifecycle_frac: float = 1.0,
) -> float:
    cap = max_rupees or float(os.getenv("MAX_RUPEES_PER_TRADE", "1000"))
    scalar = safety_scalar if safety_scalar is not None else float(os.getenv("KELLY_SAFETY_SCALAR", "1.0"))
    f = kelly_fraction(win_rate, avg_win, avg_loss, wr_variance=wr_variance) * max(0.0, scalar)
    f *= max(0.0, min(1.0, lifecycle_frac))
    if f <= 0:
        return 0.0
    return min(cap, max(100.0, equity * f))


def kelly_fraction_for_strategy(db, strategy_id: str) -> tuple[float, float, float, float]:
    """Returns (win_rate, avg_win, avg_loss, wr_variance) for router sizing."""
    from .strategy_stats import kelly_inputs_for_strategy

    wr, aw, al = kelly_inputs_for_strategy(db, strategy_id)
    var = win_rate_variance(db, strategy_id) if db else 0.25
    return wr, aw, al, var

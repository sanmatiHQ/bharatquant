"""Fractional Kelly position sizing — capped."""
from __future__ import annotations

import os


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float, fraction: float = 0.25) -> float:
    if avg_loss <= 0 or win_rate <= 0:
        return 0.0
    b = avg_win / avg_loss
    q = 1 - win_rate
    kelly = (win_rate * b - q) / b if b else 0.0
    kelly = max(0.0, min(kelly, 1.0))
    return kelly * fraction


def rupees_from_kelly(
    equity: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    max_rupees: float | None = None,
) -> float:
    cap = max_rupees or float(os.getenv("MAX_RUPEES_PER_TRADE", "1000"))
    f = kelly_fraction(win_rate, avg_win, avg_loss)
    return min(cap, max(100.0, equity * f * 0.02))

"""Historical VaR circuit breaker."""
from __future__ import annotations

import os
from typing import List

import numpy as np


def historical_var(returns: List[float], alpha: float = 0.05) -> float:
    if len(returns) < 10:
        return 0.0
    arr = np.array(returns, dtype=float)
    return float(-np.quantile(arr, alpha))


def var_breach(returns: List[float], equity: float, limit_pct: float | None = None) -> bool:
    limit = limit_pct or float(os.getenv("VAR_LIMIT_PCT", "3"))
    var = historical_var(returns)
    return var * 100 >= limit and equity > 0

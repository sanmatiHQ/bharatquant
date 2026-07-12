"""
Portfolio sizing — inverse-vol weights (skfolio MeanRisk idea without heavy deps).

Verified: SilvioBaratto/optimizer uses skfolio.measures + mean_risk; we use
equal-risk (1/vol) for ≤5 CNC names after pre-open screen.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def inverse_vol_weights(close_df: pd.DataFrame, max_names: int = 5) -> Dict[str, float]:
    """
    close_df: columns = symbols, index = dates (daily closes from Kite OHLC only).
    Returns weights summing to 1.0.
    """
    if close_df.empty or close_df.shape[1] == 0:
        return {}
    rets = close_df.pct_change().dropna(how="all")
    if rets.empty:
        n = min(max_names, close_df.shape[1])
        syms = list(close_df.columns[:n])
        w = 1.0 / len(syms)
        return {s: w for s in syms}
    vol = rets.std().replace(0, np.nan).dropna()
    if vol.empty:
        return {}
    top = vol.nsmallest(max(len(vol), max_names)).head(max_names).index.tolist()
    inv = 1.0 / vol.loc[top]
    total = float(inv.sum())
    return {str(s): float(inv[s] / total) for s in top}


def rupee_qty_map(
    weights: Dict[str, float],
    prices: Dict[str, float],
    total_budget: float,
    *,
    min_qty: int = 1,
) -> Dict[str, int]:
    """Map rupee budget to integer share quantities."""
    out: Dict[str, int] = {}
    for sym, w in weights.items():
        px = prices.get(sym, 0.0)
        if px <= 0:
            continue
        budget = total_budget * w
        qty = max(min_qty, int(budget // px))
        if qty * px <= total_budget * 1.05:
            out[sym] = qty
    return out

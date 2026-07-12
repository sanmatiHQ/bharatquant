"""4-state regime classifier — rolling vol + trend (HMM surrogate, numpy-only)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass
class RegimeState:
    label: str  # BULL | BEAR | SIDEWAYS | HIGH_VOL
    confidence: float


def classify_regime(returns: List[float], vix: float = 0.0) -> RegimeState:
    if len(returns) < 5:
        return RegimeState("SIDEWAYS", 0.5)
    arr = np.array(returns[-20:], dtype=float)
    mu = float(arr.mean())
    vol = float(arr.std()) if len(arr) > 1 else 0.0
    ann_vol = vol * np.sqrt(252)
    if vix > 22 or ann_vol > 0.28:
        return RegimeState("HIGH_VOL", min(1.0, ann_vol))
    if mu > 0.001:
        return RegimeState("BULL", min(1.0, abs(mu) * 100))
    if mu < -0.001:
        return RegimeState("BEAR", min(1.0, abs(mu) * 100))
    return RegimeState("SIDEWAYS", 0.6)


def regime_strategy_whitelist(regime: str) -> set[str]:
    base = {"stop_loss_guard", "fii_regime"}
    if regime == "BULL":
        return base | {"combined_momentum", "turtle_breakout", "gift_gap", "opening_range", "quality_momentum"}
    if regime == "BEAR":
        return base | {"short_term_reversal", "vwap_reversion", "fii_regime"}
    if regime == "HIGH_VOL":
        return base | {"vwap_reversion", "stop_loss_guard", "iv_premium_sell"}
    return base | {"combined_momentum", "short_term_reversal", "pairs_stat_arb"}

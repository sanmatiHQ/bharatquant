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


def normalize_regime(regime: str) -> str:
    """Map ingest labels (RISK_ON/OFF, NEUTRAL) to classifier buckets."""
    key = (regime or "SIDEWAYS").upper()
    return {
        "RISK_ON": "BULL",
        "RISK_OFF": "BEAR",
        "NEUTRAL": "SIDEWAYS",
    }.get(key, key)


def regime_strategy_whitelist(regime: str) -> set[str]:
    """Profit-smart: activate strategies that fit the current market regime."""
    r = normalize_regime(regime)
    advanced = {
        "macro_confluence",
        "gift_fii_sync",
        "volume_breakout",
        "bollinger_squeeze",
        "dual_momentum_pro",
        "fii_divergence",
        "vwap_volume_confirm",
        "crude_energy_beta",
        "rsi_regime_adaptive",
        "adaptive_alpha",
        "strategy_lab",
        "sector_rotation",
        "options_greeks",
    }
    core = {
        "stop_loss_guard",
        "fii_regime",
        "opening_range",
        "affordable_momentum",
        "fast_snapshot",
        "vwap_reversion",
        "pairs_stat_arb",
    } | advanced
    if r == "BULL":
        return core | {
            "combined_momentum",
            "turtle_breakout",
            "gift_gap",
            "quality_momentum",
            "bulk_accumulation",
            "insider_cluster",
        }
    if r == "BEAR":
        return core | {
            "short_term_reversal",
            "iv_premium_sell",
            "global_risk_beta",
            "cash_futures_basis",
            "expiry_gamma",
        }
    if r == "HIGH_VOL":
        return core | {
            "iv_premium_sell",
            "expiry_gamma",
            "earnings_vol",
            "global_risk_beta",
        }
    # SIDEWAYS / NEUTRAL — pursue profit across momentum + mean-reversion + events
    return core | {
        "combined_momentum",
        "short_term_reversal",
        "turtle_breakout",
        "gift_gap",
        "quality_momentum",
        "bulk_accumulation",
        "insider_cluster",
    }

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
        "BULL_TREND": "BULL",
        "BEAR_TREND": "BEAR",
        "HIGH_VOL": "HIGH_VOL",
    }.get(key, key)


def recent_index_closes(db, symbol: str = "NIFTYBEES", limit: int = 60) -> List[float]:
    """Recent closes for pre-market regime classification."""
    sym = symbol.replace("NSE:", "")
    for interval in ("1d", "5m"):
        rows = db._conn.execute(
            "SELECT close FROM bar_log WHERE symbol=? AND interval=? ORDER BY ts DESC LIMIT ?",
            (sym, interval, limit),
        ).fetchall()
        if len(rows) >= 10:
            return [float(r["close"]) for r in reversed(rows)]
    return []


def classify_regime_from_prices(closes: np.ndarray, vix: float = 0.0) -> RegimeState:
    """Price + VIX regime for RL policy hot-swap (08:45 pre-market)."""
    if len(closes) < 10:
        return RegimeState("SIDEWAYS", 0.5)
    short_ma = float(np.mean(closes[-10:]))
    long_ma = float(np.mean(closes[-50:])) if len(closes) >= 50 else float(np.mean(closes))
    if long_ma <= 0:
        return RegimeState("SIDEWAYS", 0.5)
    pct_distance = (short_ma - long_ma) / long_ma
    if vix > 22.0:
        return RegimeState("HIGH_VOL", min(1.0, vix / 30.0))
    if pct_distance > 0.015:
        return RegimeState("BULL", min(1.0, abs(pct_distance) * 50))
    if pct_distance < -0.015:
        return RegimeState("BEAR", min(1.0, abs(pct_distance) * 50))
    return RegimeState("SIDEWAYS", 0.6)


def regime_policy_version(regime: str) -> str:
    """Folder name under models/rl/regimes/{REGIME}/policy.npz."""
    r = normalize_regime(regime)
    return {
        "BULL": "BULL",
        "BEAR": "BEAR",
        "SIDEWAYS": "SIDEWAYS",
        "HIGH_VOL": "HIGH_VOL",
    }.get(r, "SIDEWAYS")


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

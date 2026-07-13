"""Encode market context + signal into fixed-size RL state vector (multimodal)."""
from __future__ import annotations

import math
from typing import Any

REGIME_MAP = {"RISK_OFF": -1.0, "NEUTRAL": 0.0, "RISK_ON": 1.0, "SIDEWAYS": 0.0, "BEAR": -0.8, "BULL": 0.8}
STATE_DIM = 16

_KEYS = (
    "score",
    "confidence",
    "regime",
    "fii",
    "gift",
    "vix",
    "pos_frac",
    "has_symbol",
    "llm_bias",
    "spread_bps",
    "futures_oi_chg",
    "us_vix_chg",
    "nikkei_chg",
    "hang_seng_chg",
    "hold_minutes_norm",
    "budget_remaining_frac",
)


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def encode_state_from_dict(
    d: dict,
    *,
    score: float = 0.0,
    confidence: float = 0.0,
    pos_frac: float = 0.0,
    has_symbol: bool = False,
    budget_remaining_frac: float = 1.0,
    hold_minutes: float = 0.0,
) -> list[float]:
    regime = REGIME_MAP.get(str(d.get("regime", "NEUTRAL")), 0.0)
    fii = float(d.get("fii_net_cr", d.get("fii", 0)) or 0) / 5000.0
    gift = float(d.get("gift_nifty_change_pct", d.get("gift", 0)) or 0) / 5.0
    vix = float(d.get("india_vix", d.get("vix", 0)) or 0) / 30.0
    return [
        _clamp(score, -1.0, 1.0),
        max(0.0, min(1.0, confidence)),
        _clamp(regime),
        _clamp(fii),
        _clamp(gift),
        max(0.0, min(1.0, vix)),
        max(0.0, min(1.0, pos_frac)),
        1.0 if has_symbol else 0.0,
        _clamp(float(d.get("llm_bias", 0) or 0)),
        max(0.0, min(1.0, float(d.get("spread_bps", 0) or 0) / 50.0)),
        _clamp(float(d.get("futures_oi_chg", 0) or 0) / 10.0),
        _clamp(float(d.get("us_vix_chg", 0) or 0) / 10.0),
        _clamp(float(d.get("nikkei_chg", 0) or 0) / 5.0),
        _clamp(float(d.get("hang_seng_chg", 0) or 0) / 5.0),
        max(0.0, min(1.0, hold_minutes / 240.0)),
        max(0.0, min(1.0, budget_remaining_frac)),
    ]


def encode_state(
    ctx: Any,
    *,
    symbol: str = "",
    confidence: float = 0.0,
    score: float = 0.0,
    db: Any = None,
    hold_minutes: float = 0.0,
) -> list[float]:
    regime = getattr(ctx, "regime", "NEUTRAL")
    pos_n = len(getattr(ctx, "positions", {}) or {})
    spread = float(getattr(ctx, "spread_bps", {}).get(symbol.replace("NSE:", ""), 0) if hasattr(ctx, "spread_bps") else 0)
    if db and symbol:
        from ..data.depth_store import latest_spread_bps

        spread = latest_spread_bps(db, symbol)
    budget_frac = 1.0
    if db:
        from ..ops.budget_gate import effective_daily_max, remaining_budget

        em = effective_daily_max(db)
        budget_frac = remaining_budget(db) / em if em > 0 else 0.0
    d = {
        "regime": regime,
        "fii_net_cr": getattr(ctx, "fii_net_cr", 0),
        "gift_nifty_change_pct": getattr(ctx, "gift_nifty_change_pct", 0),
        "india_vix": getattr(ctx, "india_vix", 0),
        "llm_bias": getattr(ctx, "llm_bias", 0),
        "spread_bps": spread,
        "futures_oi_chg": getattr(ctx, "futures_oi_chg", 0),
        "us_vix_chg": getattr(ctx, "us_vix_chg", 0),
        "nikkei_chg": getattr(ctx, "nikkei_chg", 0),
        "hang_seng_chg": getattr(ctx, "hang_seng_chg", 0),
    }
    return encode_state_from_dict(
        d,
        score=score,
        confidence=confidence,
        pos_frac=min(1.0, pos_n / 5.0),
        has_symbol=bool(symbol),
        budget_remaining_frac=budget_frac,
        hold_minutes=hold_minutes,
    )


def state_to_dict(vec: list[float]) -> dict:
    return dict(zip(_KEYS, vec))


def action_index(action: str) -> int:
    return {"hold": 0, "buy": 1, "sell": 2}.get(action.lower(), 0)


def index_action(idx: int) -> str:
    return ("hold", "buy", "sell")[max(0, min(2, idx))]

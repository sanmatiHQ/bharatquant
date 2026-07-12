"""Encode market context + signal into fixed-size RL state vector."""
from __future__ import annotations

import math
from typing import Any

REGIME_MAP = {"RISK_OFF": -1.0, "NEUTRAL": 0.0, "RISK_ON": 1.0, "SIDEWAYS": 0.0}
STATE_DIM = 8


def encode_state(ctx: Any, *, symbol: str = "", confidence: float = 0.0, score: float = 0.0) -> list[float]:
    regime = REGIME_MAP.get(str(getattr(ctx, "regime", "NEUTRAL")), 0.0)
    fii = float(getattr(ctx, "fii_net_cr", 0) or 0) / 5000.0
    gift = float(getattr(ctx, "gift_nifty_change_pct", 0) or 0) / 5.0
    vix = float(getattr(ctx, "india_vix", 0) or 0) / 30.0
    pos_n = len(getattr(ctx, "positions", {}) or {})
    return [
        max(-1.0, min(1.0, score)),
        max(0.0, min(1.0, confidence)),
        regime,
        max(-1.0, min(1.0, fii)),
        max(-1.0, min(1.0, gift)),
        max(0.0, min(1.0, vix)),
        min(1.0, pos_n / 5.0),
        1.0 if symbol else 0.0,
    ]


def state_to_dict(vec: list[float]) -> dict:
    keys = ["score", "confidence", "regime", "fii", "gift", "vix", "pos_frac", "has_symbol"]
    return dict(zip(keys, vec))


def action_index(action: str) -> int:
    return {"hold": 0, "buy": 1, "sell": 2}.get(action.lower(), 0)


def index_action(idx: int) -> str:
    return ("hold", "buy", "sell")[max(0, min(2, idx))]

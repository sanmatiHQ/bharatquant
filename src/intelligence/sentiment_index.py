"""India fear/greed composite — VIX, FII, GIFT, LLM, retail divergence."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..strategies.base import MarketContext


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _vix_component(vix: float) -> float:
    """High VIX → fear (low score). Typical India VIX range ~10–35."""
    if vix <= 0:
        return 50.0
    return _clamp(100.0 - (vix - 11.0) * 3.8)


def _fii_component(fii_cr: float) -> float:
    return _clamp(50.0 + math.tanh(fii_cr / 800.0) * 28.0)


def _gift_component(gift_pct: float) -> float:
    return _clamp(50.0 + gift_pct * 22.0)


def _llm_component(bias: float) -> float:
    return _clamp(50.0 + float(bias) * 35.0)


def _retail_divergence_component(client_net: float, fii_net: float) -> float:
    """Retail buying while FII selling → contrarian fear; aligned flows → greed."""
    gap = client_net - fii_net
    return _clamp(50.0 - math.tanh(gap / 5_000_000.0) * 18.0)


def sentiment_label(index: float) -> str:
    if index >= 75:
        return "Extreme Greed"
    if index >= 60:
        return "Greed"
    if index >= 40:
        return "Neutral"
    if index >= 25:
        return "Fear"
    return "Extreme Fear"


def compute_fear_greed(ctx: "MarketContext") -> tuple[float, str]:
    """
    Composite 0–100 index (CNN-style): 0 = extreme fear, 100 = extreme greed.
    Weights tuned for NSE: VIX heaviest, then FII, GIFT, LLM, retail divergence.
    """
    vix = float(getattr(ctx, "india_vix", 0) or 0)
    fii = float(getattr(ctx, "fii_net_cr", 0) or 0)
    gift = float(getattr(ctx, "gift_nifty_change_pct", 0) or 0)
    llm = float(getattr(ctx, "llm_bias", 0) or 0)
    client = float(getattr(ctx, "participant_client_net", 0) or 0)
    fii_oi = float(getattr(ctx, "participant_fii_net", 0) or 0)

    parts = [
        (_vix_component(vix), 0.30),
        (_fii_component(fii), 0.25),
        (_gift_component(gift), 0.15),
        (_llm_component(llm), 0.15),
        (_retail_divergence_component(client, fii_oi), 0.15),
    ]
    total_w = sum(w for _, w in parts)
    index = sum(s * w for s, w in parts) / total_w if total_w else 50.0
    index = round(_clamp(index), 1)
    return index, sentiment_label(index)

"""Fear/greed regime — contrarian at extremes, momentum in neutral band."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class SentimentRegimeStrategy:
    """India fear/greed composite drives defensive/aggressive posture."""

    id = "sentiment_regime"
    listens_to = {
        EventType.SESSION_OPEN,
        EventType.BAR_CLOSE_5M,
        EventType.IV_UPDATE,
        EventType.FII_DII_UPDATE,
        EventType.LLM_BIAS_UPDATE,
    }

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        fg = float(ctx.fear_greed_index)
        label = ctx.sentiment_label

        if event.type == EventType.SESSION_OPEN:
            if fg <= 22 and label in ("Extreme Fear", "Fear"):
                conf = min(0.78, 0.62 + (25 - fg) / 50)
                return Signal(self.id, "NIFTYBEES", "BUY", "CNC", conf, f"fear_bounce_{fg:.0f}")
            if fg >= 78 and label in ("Extreme Greed", "Greed"):
                return Signal(self.id, "NIFTYBEES", "SELL", "MIS", 0.66, f"greed_trim_{fg:.0f}")
            return None

        if event.type != EventType.BAR_CLOSE_5M:
            return None
        sym = (event.symbol or "").replace("NSE:", "")
        if not sym or not ctx.market_open:
            return None
        p = event.payload or {}
        r3m = float(p.get("r3m", 0))
        if fg <= 20 and r3m < -0.004:
            return Signal(self.id, sym, "BUY", "MIS", 0.7, "extreme_fear_dip")
        if fg >= 80 and r3m > 0.005:
            return Signal(self.id, sym, "SELL", "MIS", 0.64, "extreme_greed_fade")
        return None

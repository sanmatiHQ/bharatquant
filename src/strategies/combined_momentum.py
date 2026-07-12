"""Combined relative + absolute momentum — India outperforms price-only (Nigam & Pandey 2023)."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class CombinedMomentumStrategy:
    id = "combined_momentum"
    listens_to = {EventType.BAR_CLOSE_5M, EventType.FII_DII_UPDATE}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if event.type == EventType.FII_DII_UPDATE:
            ctx.fii_net_cr = float(event.payload.get("fii_net", 0))
            ctx.dii_net_cr = float(event.payload.get("dii_net", 0))
            return None
        r3m = float(event.payload.get("r3m", 0))
        r1m = float(event.payload.get("r1m", 0))
        rsi = float(event.payload.get("rsi", 50))
        # Relative strength (vs zero) + absolute trend alignment
        rel = r3m - r1m
        if r3m > 0.05 and rel > 0 and rsi < 70 and ctx.fii_net_cr > -2000:
            conf = min(0.95, 0.5 + r3m)
            return Signal(self.id, event.symbol, "BUY", "CNC", conf, "combined_mom_rel_abs")
        return None

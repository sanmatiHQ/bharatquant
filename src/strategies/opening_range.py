"""Opening range breakout — fires on TICK when range breaks, not at fixed clock."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class OpeningRangeStrategy:
    id = "opening_range"
    listens_to = {EventType.TICK, EventType.BAR_CLOSE_5M, EventType.SESSION_PRE_OPEN}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = event.symbol
        if not sym:
            return None
        if event.type in (EventType.SESSION_PRE_OPEN, EventType.BAR_CLOSE_5M):
            hi = float(event.payload.get("high", event.price))
            lo = float(event.payload.get("low", event.price))
            if hi > 0 and lo > 0:
                ctx.orb_high[sym] = max(ctx.orb_high.get(sym, lo), hi)
                ctx.orb_low[sym] = min(ctx.orb_low.get(sym, hi), lo)
            return None
        if event.type == EventType.TICK:
            hi = ctx.orb_high.get(sym)
            lo = ctx.orb_low.get(sym)
            if hi is None or lo is None or hi <= lo:
                return None
            px = event.price
            if px > hi:
                return Signal(self.id, sym, "BUY", "MIS", 0.7, "orb_break_up")
            if px < lo:
                return Signal(self.id, sym, "SELL", "MIS", 0.65, "orb_break_down")
        return None

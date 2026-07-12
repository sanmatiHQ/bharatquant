"""GIFT Nifty overnight gap bias before NSE open — signal only, CNC entry on SESSION_OPEN."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class GiftGapStrategy:
    id = "gift_gap"
    listens_to = {EventType.GIFT_TICK, EventType.SESSION_OPEN, EventType.PREOPEN_PRICE}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if event.type == EventType.GIFT_TICK:
            ctx.gift_nifty_change_pct = float(event.payload.get("change_pct", 0))
            return None
        if event.type in (EventType.SESSION_OPEN, EventType.PREOPEN_PRICE):
            gap = ctx.gift_nifty_change_pct
            if gap > 0.4:
                return Signal(self.id, "NIFTYBEES", "BUY", "CNC", min(0.9, 0.6 + gap / 2), "gift_gap_up")
            if gap < -0.4:
                return Signal(self.id, "NIFTYBEES", "SELL", "CNC", min(0.9, 0.6 + abs(gap) / 2), "gift_gap_down")
        return None

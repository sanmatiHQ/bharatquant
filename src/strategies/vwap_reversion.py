"""VWAP mean reversion — institutional desk pattern, MIS rail."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class VwapReversionStrategy:
    id = "vwap_reversion"
    listens_to = {EventType.TICK, EventType.VWAP_CROSS}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = event.symbol
        vwap = ctx.session_vwap.get(sym) or float(event.payload.get("vwap", 0))
        if vwap <= 0 or not sym:
            return None
        ctx.session_vwap[sym] = vwap
        dev = (event.price - vwap) / vwap * 100
        if dev < -1.5:
            return Signal(self.id, sym, "BUY", "MIS", 0.66, "vwap_below")
        if dev > 1.5:
            return Signal(self.id, sym, "SELL", "MIS", 0.64, "vwap_above")
        return None

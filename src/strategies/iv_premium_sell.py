"""IV rank premium sell — covered call style signal (defined risk)."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class IvPremiumSellStrategy:
    id = "iv_premium_sell"
    listens_to = {EventType.IV_UPDATE, EventType.TICK}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if event.type == EventType.IV_UPDATE:
            ctx.india_vix = float(event.payload.get("vix", event.payload.get("india_vix", 0)))
            return None
        if ctx.india_vix < 18:
            return None
        sym = event.symbol.replace("NSE:", "")
        if sym not in ctx.positions:
            return None
        if ctx.india_vix >= 22:
            return Signal(self.id, sym, "HEDGE", "OPT", 0.7, f"iv_rank_{ctx.india_vix:.1f}")
        return None

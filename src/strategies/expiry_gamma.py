"""Expiry week gamma / OI pinning awareness."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class ExpiryGammaStrategy:
    id = "expiry_gamma"
    listens_to = {EventType.IV_UPDATE, EventType.TICK}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        if today.weekday() != 3:  # Thursday expiry week
            return None
        if event.type != EventType.TICK:
            return None
        sym = event.symbol.replace("NSE:", "")
        if sym not in ("NIFTY", "BANKNIFTY", "NIFTYBEES"):
            return None
        if ctx.india_vix > 20:
            return Signal(self.id, sym, "HEDGE", "OPT", 0.6, "expiry_high_iv")
        return None

"""Quality + momentum — ROE filter from fundamentals_cache."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class QualityMomentumStrategy:
    id = "quality_momentum"
    listens_to = {EventType.TICK, EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = event.symbol.replace("NSE:", "")
        if not sym or event.price <= 0:
            return None
        roe = float(event.payload.get("roe", 0) or 0)
        if roe < 15 and ctx.regime != "RISK_ON":
            return None
        if ctx.regime in ("RISK_OFF", "BEAR"):
            return None
        mom = float(event.payload.get("r1m", event.payload.get("momentum", 0)) or 0)
        if mom > 0.05 or (roe >= 18 and mom > 0.02):
            conf = min(0.85, 0.5 + mom)
            return Signal(self.id, sym, "BUY", "CNC", conf, f"quality_roe_{roe:.0f}_mom_{mom:.2f}")
        return None

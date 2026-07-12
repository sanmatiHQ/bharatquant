"""Global macro risk beta filter — reduces risk when US/crude risk-off."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class GlobalRiskBetaStrategy:
    id = "global_risk_beta"
    listens_to = {EventType.GIFT_SESSION_CHANGE, EventType.GIFT_TICK}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        p = event.payload or {}
        us = float(p.get("us_sp", 0))
        crude = float(p.get("crude", 0))
        usd = float(p.get("usd_inr", 0))
        risk_off = us < -0.5 or crude > 2.0 or usd > 0.3
        if risk_off:
            ctx.regime = "RISK_OFF"
            return Signal(self.id, "NIFTYBEES", "SELL", "CNC", 0.7, f"global_risk_off_us{us:.2f}")
        if us > 0.4 and crude < 0:
            ctx.regime = "RISK_ON"
        return None

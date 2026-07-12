"""FII momentum vs DII contrarian — macro paper 2012-2024 India."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class FiiRegimeStrategy:
    id = "fii_regime"
    listens_to = {EventType.FII_DII_UPDATE, EventType.GIFT_TICK}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if event.type == EventType.GIFT_TICK:
            ctx.gift_nifty_change_pct = float(event.payload.get("change_pct", 0))
            return None
        fii = float(event.payload.get("fii_net", ctx.fii_net_cr))
        dii = float(event.payload.get("dii_net", ctx.dii_net_cr))
        ctx.fii_net_cr, ctx.dii_net_cr = fii, dii
        if fii < -3000 and dii < 0:
            ctx.regime = "RISK_OFF"
            return Signal(self.id, "NIFTY", "HEDGE", "NRML", 0.75, "fii_dump_both_sell")
        if fii > 1000 and dii > 0:
            ctx.regime = "RISK_ON"
        return None

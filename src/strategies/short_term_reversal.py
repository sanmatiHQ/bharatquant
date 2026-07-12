"""5-day short-term reversal — retail overreaction (IMMR-H India journal)."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class ShortTermReversalStrategy:
    id = "short_term_reversal"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        ret_5d = float(event.payload.get("ret_5d", 0))
        if ret_5d < -0.06:
            return Signal(self.id, event.symbol, "BUY", "CNC", 0.68, "str_reversal_oversold")
        if ret_5d > 0.08:
            return Signal(self.id, event.symbol, "SELL", "CNC", 0.6, "str_reversal_overbought")
        return None

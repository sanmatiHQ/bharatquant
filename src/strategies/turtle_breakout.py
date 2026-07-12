"""Donchian / Turtle breakout on BAR_CLOSE."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class TurtleBreakoutStrategy:
    id = "turtle_breakout"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        high_20 = float(event.payload.get("high_20", 0))
        low_20 = float(event.payload.get("low_20", 0))
        close = event.price or float(event.payload.get("close", 0))
        if close > high_20 > 0:
            return Signal(self.id, event.symbol, "BUY", "CNC", 0.72, "turtle_20d_high")
        if close < low_20 and low_20 > 0:
            return Signal(self.id, event.symbol, "SELL", "CNC", 0.65, "turtle_20d_low")
        return None

"""Real-time stop-loss on TICK — never cron."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class StopLossGuardStrategy:
    id = "stop_loss_guard"
    listens_to = {EventType.TICK, EventType.STOP_BREACH, EventType.TAKE_PROFIT}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if event.type in (EventType.STOP_BREACH, EventType.TAKE_PROFIT):
            reason = event.payload.get("reason", "stop_breach")
            return Signal(
                self.id,
                event.symbol,
                "SELL",
                event.payload.get("rail", "CNC"),
                1.0,
                reason,
            )
        sym = event.symbol
        pos = ctx.positions.get(sym)
        if not pos:
            return None
        avg = float(pos.get("avg_price", 0))
        sl_pct = float(pos.get("stop_loss_pct", 4.0))
        if avg <= 0:
            return None
        drop = (avg - event.price) / avg * 100
        if drop >= sl_pct:
            return Signal(self.id, sym, "SELL", pos.get("rail", "CNC"), 1.0, f"stop_{drop:.2f}pct")
        return None

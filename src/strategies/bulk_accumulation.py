"""Bulk deal accumulation follow."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class BulkAccumulationStrategy:
    id = "bulk_accumulation"
    listens_to = {EventType.BLOCK_DEAL}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        p = event.payload or {}
        side = str(p.get("buySell", p.get("clientName", ""))).lower()
        qty = float(p.get("qty", p.get("quantity", 0)) or 0)
        if qty < 100_000:
            return None
        if "buy" not in side and "acquisition" not in side:
            return None
        sym = event.symbol.replace("NSE:", "")
        if not sym:
            return None
        return Signal(self.id, sym, "BUY", "CNC", 0.68, f"bulk_qty_{int(qty)}")

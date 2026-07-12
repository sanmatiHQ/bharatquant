"""Cash-futures basis arb signal."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class CashFuturesBasisStrategy:
    id = "cash_futures_basis"
    listens_to = {EventType.TICK, EventType.IV_UPDATE}

    def __init__(self) -> None:
        self._spot: dict[str, float] = {}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = event.symbol.replace("NSE:", "")
        fut_sym = event.payload.get("fut_symbol", "")
        if event.type == EventType.TICK and sym and event.price > 0:
            self._spot[sym] = event.price
            return None
        basis = float(event.payload.get("basis_pct", 0) or 0)
        if abs(basis) < 0.5:
            return None
        target = fut_sym or sym
        if basis > 1.0:
            return Signal(self.id, target, "SELL", "NRML", 0.65, f"basis_high_{basis:.2f}")
        if basis < -1.0:
            return Signal(self.id, target, "BUY", "NRML", 0.65, f"basis_low_{basis:.2f}")
        return None

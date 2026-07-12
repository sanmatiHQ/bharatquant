"""Earnings / results volatility event strategy."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy

_EARNINGS_KW = ("result", "earnings", "quarter", "financial", "profit", "revenue", "dividend")


class EarningsVolStrategy:
    id = "earnings_vol"
    listens_to = {EventType.NEWS_ALERT}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        p = event.payload or {}
        desc = str(p.get("desc", p.get("subject", p.get("summary", "")))).lower()
        if not any(k in desc for k in _EARNINGS_KW):
            return None
        sym = event.symbol.replace("NSE:", "")
        if not sym:
            return None
        if ctx.india_vix > 18:
            return Signal(self.id, sym, "HEDGE", "OPT", 0.62, "earnings_high_iv")
        return Signal(self.id, sym, "SELL", "MIS", 0.55, "earnings_vol_reduce")

"""Earnings / results volatility event strategy."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from ..intelligence.corporate_activity import classify_corp_category
from .base import MarketContext, Signal, Strategy

_EARNINGS_KW = ("result", "earnings", "quarter", "financial", "profit", "revenue")


class EarningsVolStrategy:
    id = "earnings_vol"
    listens_to = {EventType.NEWS_ALERT}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        p = event.payload or {}
        desc = str(p.get("desc", p.get("subject", p.get("summary", ""))))
        cat = classify_corp_category(desc)
        if cat == "dividend":
            sym = event.symbol.replace("NSE:", "")
            if not sym:
                return None
            return Signal(self.id, sym, "BUY", "CNC", 0.68, f"dividend_capture: {desc[:80]}")
        desc_l = desc.lower()
        if not any(k in desc_l for k in _EARNINGS_KW):
            return None
        sym = event.symbol.replace("NSE:", "")
        if not sym:
            return None
        if ctx.india_vix > 18:
            return Signal(self.id, sym, "HEDGE", "OPT", 0.62, "earnings_high_iv")
        return Signal(self.id, sym, "SELL", "MIS", 0.55, "earnings_vol_reduce")

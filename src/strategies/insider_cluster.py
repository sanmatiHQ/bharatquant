"""Insider cluster — promoter buy filings."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from ..intelligence.corporate_activity import normalize_insider
from .base import MarketContext, Signal, Strategy


class InsiderClusterStrategy:
    id = "insider_cluster"
    listens_to = {EventType.INSIDER_FILING}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        p = event.payload or {}
        acq = str(p.get("acqMode", p.get("buySell", ""))).lower()
        person = str(p.get("personName", "")).lower()
        if "buy" not in acq and "acquisition" not in acq:
            return None
        if "promoter" not in person and "director" not in person:
            return None
        sym = event.symbol.replace("NSE:", "")
        if not sym:
            return None
        norm = normalize_insider(p)
        return Signal(
            self.id,
            sym,
            "BUY",
            "CNC",
            0.72,
            norm.get("reason", "insider_promoter_buy"),
        )

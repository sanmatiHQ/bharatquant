"""Options Greeks proxy — IV rank + delta skew for paper/live hedges."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class OptionsGreeksStrategy:
    id = "options_greeks"
    listens_to = {EventType.IV_UPDATE, EventType.BAR_CLOSE_5M}

    def __init__(self, db=None) -> None:
        self.db = db

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        vix = ctx.india_vix
        if event.type == EventType.IV_UPDATE:
            if vix > 24:
                return Signal(self.id, "NIFTY", "HEDGE", "OPT", 0.72, f"vix_high_{vix:.1f}")
            return None
        if vix < 14 or not self.db:
            return None
        sym = (event.symbol or "").replace("NSE:", "")
        if sym not in ("NIFTYBEES", "NIFTY"):
            return None
        row = self.db._conn.execute(
            """
            SELECT strike, iv, ltp FROM option_iv
            WHERE symbol='NIFTY' AND option_type='CE'
            ORDER BY iv DESC LIMIT 1
            """
        ).fetchone()
        if not row or float(row["iv"] or 0) < 18:
            return None
        return Signal(self.id, "NIFTY", "SELL", "OPT", 0.68, "iv_premium_fade_ce")

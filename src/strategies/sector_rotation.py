"""Sector rotation — buy leaders, fade laggards within sector relative strength."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class SectorRotationStrategy:
    id = "sector_rotation"
    listens_to = {EventType.BAR_CLOSE_5M}

    def __init__(self, db=None) -> None:
        self.db = db
        self._sector_ret: Dict[str, list[float]] = defaultdict(list)

    def _sector_for(self, sym: str) -> str:
        if self.db is None:
            return "UNKNOWN"
        row = self.db._conn.execute(
            "SELECT sector FROM symbol_sectors WHERE symbol=?", (sym,)
        ).fetchone()
        return str(row["sector"]) if row else "UNKNOWN"

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = (event.symbol or "").replace("NSE:", "")
        if not sym:
            return None
        p = event.payload or {}
        r3m = float(p.get("r3m", 0))
        sector = self._sector_for(sym)
        if sector == "UNKNOWN":
            return None
        hist = self._sector_ret[sector]
        hist.append(r3m)
        if len(hist) > 30:
            self._sector_ret[sector] = hist[-30:]
        if len(hist) < 5:
            return None
        sector_avg = sum(hist[-5:]) / 5
        rel = r3m - sector_avg
        if rel > 0.004 and r3m > 0 and ctx.regime in ("RISK_ON", "BULL", "NEUTRAL"):
            return Signal(self.id, sym, "BUY", "CNC", 0.7, f"sector_lead_{sector[:12]}")
        if rel < -0.005 and r3m < 0 and ctx.regime in ("RISK_OFF", "BEAR"):
            return Signal(self.id, sym, "SELL", "MIS", 0.66, f"sector_lag_{sector[:12]}")
        return None

"""Affordable tick momentum — paper-learn trades on names that fit per-trade cap."""
from __future__ import annotations

import os
import time
from typing import Optional
from zoneinfo import ZoneInfo

from ..events.types import EventType, MarketEvent
from ..ops.trade_sizing import can_buy_whole_share, deploy_cap_inr
from .base import MarketContext, Signal, Strategy


class AffordableMomentumStrategy:
    id = "affordable_momentum"
    listens_to = {EventType.TICK, EventType.SESSION_PRE_OPEN}

    def __init__(self, db=None) -> None:
        self._db = db

    def _today_start_ts(self) -> int:
        tz = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
        from datetime import datetime

        now = datetime.now(tz)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(midnight.timestamp())

    def _session_open(self, sym: str, ctx: MarketContext, price: float) -> float:
        if sym in ctx.session_open and ctx.session_open[sym] > 0:
            return float(ctx.session_open[sym])
        ref = ctx.orb_low.get(sym) or ctx.orb_high.get(sym)
        if ref and ref > 0:
            ctx.session_open[sym] = float(ref)
            return float(ref)
        if self._db:
            row = self._db._conn.execute(
                """
                SELECT open FROM bar_log
                WHERE symbol=? AND interval='5m' AND ts >= ?
                ORDER BY ts ASC LIMIT 1
                """,
                (sym, self._today_start_ts()),
            ).fetchone()
            if row and float(row["open"]) > 0:
                ctx.session_open[sym] = float(row["open"])
                return float(row["open"])
        ctx.session_open[sym] = price
        return price

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = event.symbol
        if not sym or event.price <= 0:
            return None
        cash = 0.0
        if self._db:
            row = self._db._conn.execute("SELECT IFNULL(SUM(delta),0) c FROM cash_ledger").fetchone()
            cash = float(row["c"]) if row else 0.0
        if self._db and not can_buy_whole_share(event.price, deploy_cap_inr(self._db, cash)):
            return None
        if event.type == EventType.SESSION_PRE_OPEN:
            ctx.session_open[sym] = event.price
            return None
        open_px = self._session_open(sym, ctx, event.price)
        if open_px <= 0:
            return None
        move_pct = (event.price - open_px) / open_px * 100
        paper_learn = os.getenv("TRADING_PHASE", "paper_learn") == "paper_learn"
        up_thresh = 0.10 if paper_learn else 0.22
        if move_pct >= up_thresh:
            conf = min(0.82, 0.58 + move_pct * 0.08)
            return Signal(self.id, sym, "BUY", "MIS", conf, f"affordable_mom_{move_pct:.2f}pct")
        if move_pct <= -0.28 and sym in ctx.positions and int(ctx.positions[sym].get("qty", 0)) > 0:
            return Signal(self.id, sym, "SELL", "MIS", 0.62, f"affordable_exit_{move_pct:.2f}pct")
        return None

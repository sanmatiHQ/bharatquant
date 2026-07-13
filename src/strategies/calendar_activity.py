"""NSE calendar + announcement activity — learns from all declared market events."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from ..intelligence.corporate_activity import classify_corp_category
from .base import MarketContext, Signal, Strategy


def _sym(event: MarketEvent) -> str:
    return (event.symbol or "").replace("NSE:", "")


class CalendarActivityStrategy:
    """Trade/learn around NSE-declared corp actions, board meetings, calendar events."""

    id = "calendar_activity"
    listens_to = {
        EventType.CORPORATE_ACTION,
        EventType.BOARD_MEETING,
        EventType.EVENT_CALENDAR,
        EventType.BSE_ANNOUNCEMENT,
        EventType.NEWS_ALERT,
    }

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if not ctx.market_open and event.type != EventType.NEWS_ALERT:
            return None
        p = event.payload or {}
        sym = _sym(event) or str(p.get("symbol", p.get("sm_name", ""))).replace("NSE:", "")
        if not sym:
            return None
        text = " ".join(
            str(p.get(k, ""))
            for k in ("desc", "subject", "purpose", "title", "summary", "bm_desc")
        )
        cat = classify_corp_category(text)
        weights = getattr(ctx, "institutional_weights", {}) or {}
        strat_w = float((weights.get("strategies") or {}).get(self.id, 1.0))
        pattern_key = f"{event.type}:{cat}:neutral:exchange"
        pat_w = float((weights.get("patterns") or {}).get(pattern_key, 1.0))
        w = strat_w * pat_w

        if cat == "dividend" and event.type in (EventType.CORPORATE_ACTION, EventType.NEWS_ALERT):
            conf = min(0.75, 0.58 * w)
            return Signal(self.id, sym, "BUY", "CNC", conf, "dividend_capture")
        if cat == "earnings" and event.type in (EventType.BOARD_MEETING, EventType.NEWS_ALERT):
            if ctx.fear_greed_index < 35:
                return Signal(self.id, sym, "BUY", "MIS", 0.62 * w, "earnings_fear_entry")
            if ctx.fear_greed_index > 72:
                return Signal(self.id, sym, "SELL", "MIS", 0.6, "earnings_greed_fade")
        if cat in ("split", "bonus") and event.type == EventType.CORPORATE_ACTION:
            return Signal(self.id, sym, "BUY", "CNC", min(0.72, 0.6 * w), f"corp_{cat}")
        if cat == "buyback" and event.type in (EventType.CORPORATE_ACTION, EventType.NEWS_ALERT):
            return Signal(self.id, sym, "BUY", "CNC", 0.68 * w, "buyback_signal")
        if event.type == EventType.BOARD_MEETING:
            ctx.upcoming_events = (
                [{"symbol": sym, "kind": "board_meeting", "category": cat, "text": text[:80]}]
                + list(ctx.upcoming_events)
            )[:15]
        return None

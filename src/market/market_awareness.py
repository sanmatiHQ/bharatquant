"""Central market clock + fear/greed — single source of temporal/sentiment truth."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..intelligence.news_context import recent_market_headlines
from ..intelligence.sentiment_index import compute_fear_greed
from ..strategies.base import MarketContext
from ..strategies.market_session import (
    is_monthly_expiry_day,
    is_nse_open,
    ist_now,
    market_clock_snapshot,
    session_phase,
)

logger = logging.getLogger("bharatquant.market_awareness")


def refresh_market_awareness(ctx: MarketContext, db: Any = None) -> dict[str, Any]:
    """Refresh all time/date/session + sentiment fields on MarketContext."""
    snap = market_clock_snapshot()
    ctx.session_phase = snap["session_phase"]
    ctx.nse_status = getattr(ctx, "nse_status", None) or snap.get("nse_status", "Unknown")
    ctx.market_open = snap["market_open"]
    ctx.ist_date = snap["ist_date"]
    ctx.ist_time = snap["ist_time"]
    ctx.minutes_to_close = snap["minutes_to_close"]
    ctx.minutes_from_open = snap["minutes_from_open"]
    ctx.is_expiry_day = snap["is_expiry_day"]
    ctx.is_weekend = snap["is_weekend"]

    if db is not None:
        ctx.recent_headlines = recent_market_headlines(db, limit=12)

    fg, label = compute_fear_greed(ctx)
    ctx.fear_greed_index = fg
    ctx.sentiment_label = label
    return snap


async def market_clock_loop(ctx: MarketContext, db: Any, interval_sec: float = 60.0) -> None:
    """Periodic refresh so strategies/dashboard always see current IST phase."""
    while True:
        try:
            refresh_market_awareness(ctx, db)
        except Exception:
            logger.exception("market_clock_error")
        await asyncio.sleep(interval_sec)

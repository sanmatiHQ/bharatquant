"""Poll Nifty index LTP via Kite REST — feeds tick_log + bar_log for live charts."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from ..ingest.index_data import INDEX_MAP, write_index_tick
from ..ops.healthchecks import check_token
from ..strategies.market_session import ist_now, session_phase

logger = logging.getLogger("bharatquant.index_poller")

_POLL_SEC = float(os.getenv("INDEX_POLL_SEC", "30"))


def _session_active() -> bool:
    ph = session_phase()
    return ph in (
        "block_deal",
        "pre_open",
        "opening_drive",
        "morning",
        "lunch",
        "afternoon",
        "power_hour",
    )


async def poll_index_quotes_loop(db) -> None:
    """Kite LTP for Nifty 50/100 during pre-open + cash session."""
    while True:
        await asyncio.sleep(_POLL_SEC)
        if not _session_active():
            continue
        if not check_token(live=False):
            continue
        try:
            from ..data.kite_data_feed import KiteDataFeed

            feed = KiteDataFeed()
            keys = ("nifty50", "nifty100", "banknifty", "sensex")
            symbols = [INDEX_MAP[k]["kite"] for k in keys if k in INDEX_MAP]
            if not symbols:
                continue
            quotes = feed.ltp(symbols)
            now = int(time.time())
            for key in keys:
                kite_sym = INDEX_MAP[key]["kite"]
                ltp = quotes.get(kite_sym)
                if ltp and ltp > 0:
                    write_index_tick(db, INDEX_MAP[key]["db_symbol"], float(ltp), ts=now)
            logger.debug("index_poll_ok", extra={"symbols": len(quotes), "ist": ist_now().strftime("%H:%M")})
        except Exception:
            logger.exception("index_poll_error")

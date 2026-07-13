"""Batch LTP poll — parallel quote refresh for full watchlist (beyond WS cap)."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from ..data.instruments import InstrumentStore
from ..data.kite_data_feed import KiteDataFeed
from ..data.watchlist import load_watchlist_symbols
from ..db.database import DB
from ..engine.fast_snapshot import is_market_session

logger = logging.getLogger("bharatquant.batch_ltp")


async def poll_batch_ltp_loop(db: DB, universe_csv: str, interval_sec: float | None = None) -> None:
    """
    Poll Kite quote/LTP in parallel batches during session — keeps tick_log fresh for 400+ symbols.
    """
    sec = interval_sec or float(os.getenv("BATCH_LTP_INTERVAL_SEC", "12"))
    batch = int(os.getenv("BATCH_LTP_SIZE", "200"))
    store = InstrumentStore(db=db)
    store.ensure_cache(universe_csv=universe_csv)

    while True:
        try:
            if is_market_session():
                syms = load_watchlist_symbols(db)
                if syms:
                    feed = KiteDataFeed()
                    ts = int(time.time())
                    n = 0
                    for i in range(0, len(syms), batch):
                        chunk = syms[i : i + batch]
                        instruments = [f"NSE:{s}" if not s.startswith("NSE:") else s for s in chunk]
                        try:
                            quotes = await asyncio.to_thread(feed.ltp, instruments)
                            with db.tx() as conn:
                                for key, px in quotes.items():
                                    sym = key.split(":")[-1]
                                    conn.execute(
                                        "INSERT INTO tick_log(ts, symbol, ltp) VALUES (?,?,?)",
                                        (ts, sym, float(px)),
                                    )
                                    n += 1
                        except Exception:
                            logger.exception("batch_ltp_chunk_failed", extra={"offset": i})
                    if n:
                        logger.debug("batch_ltp_refreshed", extra={"symbols": n})
        except Exception:
            logger.exception("batch_ltp_loop_error")
        await asyncio.sleep(sec)

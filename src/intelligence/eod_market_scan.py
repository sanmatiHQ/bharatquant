"""Post-close EOD scan — full-market movers + swing momentum for next-day watchlist."""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from ..data.instruments import InstrumentStore
from ..data.kite_data_feed import KiteDataFeed
from ..db.database import DB
from ..screening.momentum_screener import DataUnavailableError

logger = logging.getLogger("bharatquant.eod_scan")


def _scan_one(
    sym: str,
    token: int,
    feed: KiteDataFeed,
    lookback_days: int,
) -> Optional[dict[str, Any]]:
    end = datetime.utcnow().date()
    start = end - timedelta(days=lookback_days)
    try:
        df = feed.historical(token, start.isoformat(), end.isoformat(), interval="day")
        if df is None or len(df) < 3:
            return None
        prev = float(df["close"].iloc[-2])
        last = float(df["close"].iloc[-1])
        vol = float(df["volume"].iloc[-1])
        if prev <= 0:
            return None
        day_pct = (last - prev) / prev * 100.0
        vol_avg = float(df["volume"].tail(10).mean()) if len(df) >= 10 else vol
        vol_ratio = vol / vol_avg if vol_avg > 0 else 1.0
        swing_5d = 0.0
        if len(df) >= 6:
            c5 = float(df["close"].iloc[-6])
            if c5 > 0:
                swing_5d = (last - c5) / c5 * 100.0
        score = abs(day_pct) * 0.5 + max(0.0, vol_ratio - 1.0) * 0.3 + abs(swing_5d) * 0.2
        return {
            "symbol": sym.replace("NSE:", ""),
            "day_pct": round(day_pct, 3),
            "swing_5d_pct": round(swing_5d, 3),
            "vol_ratio": round(vol_ratio, 3),
            "last_close": last,
            "eod_score": round(score, 4),
        }
    except Exception:
        return None


def run_eod_market_scan(db: DB, universe_csv: str) -> dict[str, Any]:
    """
    Parallel EOD scan across universe — rank movers, persist for tomorrow's watchlist.
    """
    workers = int(os.getenv("EOD_SCAN_WORKERS", "12"))
    lookback = int(os.getenv("EOD_SCAN_LOOKBACK_DAYS", "30"))
    top_n = int(os.getenv("EOD_SCAN_TOP_N", "200"))

    feed = KiteDataFeed()
    store = InstrumentStore(db=db)
    store.ensure_cache(universe_csv=universe_csv)
    syms = store.load_universe(universe_csv)
    logger.info("eod_scan_start", extra={"universe": len(syms), "workers": workers})

    rows: list[dict[str, Any]] = []
    errors = 0

    def _job(sym: str) -> Optional[dict[str, Any]]:
        try:
            token = store.token_for(sym)
            return _scan_one(sym, token, feed, lookback)
        except KeyError:
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_job, s): s for s in syms}
        for i, fut in enumerate(as_completed(futures), 1):
            if i % 200 == 0:
                logger.info("eod_scan_progress", extra={"done": i, "total": len(syms), "hits": len(rows)})
            try:
                r = fut.result()
                if r:
                    rows.append(r)
                else:
                    errors += 1
            except Exception:
                errors += 1

    if not rows:
        return {"ok": False, "hits": 0, "errors": errors}

    df = pd.DataFrame(rows).sort_values("eod_score", ascending=False).head(top_n)
    run_ts = int(time.time())
    gainers = df.nlargest(15, "day_pct")[["symbol", "day_pct"]].to_dict("records")
    losers = df.nsmallest(10, "day_pct")[["symbol", "day_pct"]].to_dict("records")
    swing = df.nlargest(15, "swing_5d_pct")[["symbol", "swing_5d_pct"]].to_dict("records")

    to_store = [
        (
            run_ts,
            str(r.symbol),
            float(r.eod_score),
            float(r.day_pct) / 100.0,
            float(r.swing_5d_pct) / 100.0,
            50.0,
            1,
        )
        for r in df.itertuples(index=False)
    ]
    db.record_screen(run_ts, to_store)

    summary = {
        "run_ts": run_ts,
        "hits": len(df),
        "top_gainers": gainers,
        "top_losers": losers,
        "swing_momentum": swing,
        "errors": errors,
    }
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("eod_scan_latest", json.dumps(summary)),
        )
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("last_screen_source", "eod_scan"),
        )
    logger.info("eod_scan_done", extra={"hits": len(df), "errors": errors})
    return {"ok": True, **summary}


async def run_eod_scan_async(db: DB, universe_csv: str) -> dict[str, Any]:
    import asyncio

    return await asyncio.to_thread(run_eod_market_scan, db, universe_csv)

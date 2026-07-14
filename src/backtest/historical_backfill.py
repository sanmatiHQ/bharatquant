"""Kite historical() → bar_log backfill for universe symbols lacking depth."""
from __future__ import annotations

import csv
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..data.kite_data_feed import KiteDataFeed
from ..db.database import DB

logger = logging.getLogger("bharatquant.historical_backfill")

_IST = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))

_KITE_INTERVAL = {"1d": "day", "5m": "5minute"}


def _is_main_tier_symbol(symbol: str, tradingsymbol: str) -> bool:
    sym = symbol.upper()
    ts = tradingsymbol.upper()
    skip = ("BEES", "ETF", "INAV", "NIFTY", "BANK", "SENSEX", "GOLD", "SILVER")
    return not any(x in sym or x in ts for x in skip)


def load_universe_main_tier(csv_path: str | Path) -> list[dict]:
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sym = str(r.get("symbol", "")).strip()
            ts = str(r.get("tradingsymbol", sym.replace("NSE:", ""))).strip()
            tok = int(r.get("instrument_token") or 0)
            if not sym or tok <= 0:
                continue
            if not _is_main_tier_symbol(sym, ts):
                continue
            rows.append({"symbol": sym.replace("NSE:", ""), "instrument_token": tok})
    return rows


def _bar_depth_days(db: DB, symbol: str, interval: str) -> int:
    row = db._conn.execute(
        """
        SELECT COUNT(*) AS n, MIN(ts) AS mn, MAX(ts) AS mx
        FROM bar_log WHERE symbol=? AND interval=?
        """,
        (symbol, interval),
    ).fetchone()
    n = int(row["n"] or 0)
    if n < 2:
        return 0
    return max(1, int((int(row["mx"]) - int(row["mn"])) / 86400))


def symbols_needing_backfill(
    db: DB,
    universe: list[dict],
    *,
    interval: str,
    min_days: int,
    limit: int,
) -> list[dict]:
    need: list[tuple[int, dict]] = []
    for u in universe:
        depth = _bar_depth_days(db, u["symbol"], interval)
        if depth < min_days:
            need.append((depth, u))
    need.sort(key=lambda x: x[0])
    return [u for _, u in need[:limit]]


def _persist_bars(db: DB, symbol: str, interval: str, df) -> int:
    n = 0
    with db.tx() as conn:
        for _, row in df.iterrows():
            ts = int(row["date"].timestamp())
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            vol = int(row.get("volume") or 0)
            if c <= 0:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO bar_log(ts, symbol, interval, open, high, low, close, volume)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (ts, symbol, interval, o, h, l, c, vol),
            )
            n += 1
    return n


def _fetch_range(feed: KiteDataFeed, token: int, start: datetime, end: datetime, kite_interval: str):
    return feed.historical(
        token,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        interval=kite_interval,
    )


def backfill_symbol(
    db: DB,
    feed: KiteDataFeed,
    *,
    symbol: str,
    instrument_token: int,
    interval: str,
    years: float = 2.0,
) -> int:
    kite_iv = _KITE_INTERVAL.get(interval, "day")
    now = datetime.now(_IST)
    start = now - timedelta(days=int(365 * years))
    total = 0
    if interval == "5m":
        chunk_days = 55
        cur = start
        while cur < now:
            end = min(cur + timedelta(days=chunk_days), now)
            try:
                df = _fetch_range(feed, instrument_token, cur, end, kite_iv)
                total += _persist_bars(db, symbol, interval, df)
            except Exception:
                logger.exception("backfill_chunk_failed", extra={"symbol": symbol, "from": cur.isoformat()})
            cur = end + timedelta(days=1)
            time.sleep(0.35)
    else:
        try:
            df = _fetch_range(feed, instrument_token, start, now, kite_iv)
            total += _persist_bars(db, symbol, interval, df)
        except Exception:
            logger.exception("backfill_daily_failed", extra={"symbol": symbol})
    return total


def backfill_universe(
    db: DB,
    universe_csv: str | Path,
    *,
    intervals: tuple[str, ...] = ("1d", "5m"),
    years: float = 2.0,
    min_depth_days: int = 180,
    max_symbols: int | None = None,
) -> dict:
    cap = max_symbols or int(os.getenv("HIST_BACKFILL_MAX_SYMBOLS", "80"))
    feed = KiteDataFeed()
    universe = load_universe_main_tier(universe_csv)
    summary: dict = {"symbols_attempted": 0, "bars_inserted": 0, "by_interval": {}}
    for interval in intervals:
        targets = symbols_needing_backfill(
            db, universe, interval=interval, min_days=min_depth_days, limit=cap
        )
        inserted = 0
        for u in targets:
            n = backfill_symbol(
                db,
                feed,
                symbol=u["symbol"],
                instrument_token=u["instrument_token"],
                interval=interval,
                years=years if interval == "1d" else min(years, 1.0),
            )
            inserted += n
            summary["symbols_attempted"] += 1
        summary["by_interval"][interval] = {"targets": len(targets), "bars": inserted}
        summary["bars_inserted"] += inserted
    return summary

"""Watchlist — full universe for screening, capped subset for WebSocket ticks."""
from __future__ import annotations

import os
from typing import List

from ..db.database import DB


def load_watchlist_symbols(db: DB, max_symbols: int | None = None) -> List[str]:
    """
    Priority: open positions → latest screening scores → config cap.
    Kite WS practical limit ~3000; default 200 for bandwidth.
    """
    cap = max_symbols or int(os.getenv("WS_WATCHLIST_SIZE", "200"))
    symbols: List[str] = []

    cur = db._conn.execute("SELECT symbol FROM positions WHERE qty > 0")
    for row in cur.fetchall():
        s = str(row["symbol"]).replace("NSE:", "")
        if s not in symbols:
            symbols.append(s)

    remaining = cap - len(symbols)
    if remaining > 0:
        cur = db._conn.execute("SELECT MAX(run_ts) AS ts FROM screening_results")
        ts_row = cur.fetchone()
        if ts_row and ts_row["ts"]:
            cur = db._conn.execute(
                """
                SELECT symbol FROM screening_results
                WHERE run_ts = ?
                ORDER BY momentum_score DESC
                LIMIT ?
                """,
                (int(ts_row["ts"]), remaining),
            )
            for row in cur.fetchall():
                s = str(row["symbol"]).replace("NSE:", "")
                if s not in symbols:
                    symbols.append(s)

    return symbols[:cap]


def is_watchlist_symbol(db: DB, symbol: str) -> bool:
    sym = symbol.replace("NSE:", "")
    return sym in load_watchlist_symbols(db)

"""Minimum interval between order placements — prevents HFT panic loops."""
from __future__ import annotations

import os
import time

from ..db.database import DB

KEY_LAST_ORDER_TS = "last_order_placed_ts"


def min_order_interval_sec() -> float:
    return float(os.getenv("MIN_ORDER_INTERVAL_SEC", "30"))


def can_place_order(db: DB) -> tuple[bool, float]:
    """Returns (allowed, seconds_remaining)."""
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_LAST_ORDER_TS,)).fetchone()
    last = float(row["v"]) if row and row["v"] else 0.0
    gap = min_order_interval_sec()
    elapsed = time.time() - last
    if elapsed < gap:
        return False, gap - elapsed
    return True, 0.0


def mark_order_placed(db: DB) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_LAST_ORDER_TS, str(int(time.time()))),
        )

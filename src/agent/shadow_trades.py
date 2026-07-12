"""Shadow trades — log signals without execution for calibration."""
from __future__ import annotations

import time

from ..db.database import DB
from ..strategies.base import Signal


def record_shadow(db: DB, sig: Signal, price: float) -> None:
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO shadow_trades(ts, strategy_id, symbol, action, confidence, price, reason)
            VALUES (?,?,?,?,?,?,?)
            """,
            (int(time.time()), sig.strategy_id, sig.symbol, sig.action, sig.confidence, price, sig.reason),
        )

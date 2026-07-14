"""Per-symbol session cooldown after a losing close — blocks repeat bad re-entry."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..db.database import DB

IST = timezone(timedelta(hours=5, minutes=30))


def _session_day() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def cooldown_minutes_after_loss() -> int:
    return int(os.getenv("SYMBOL_LOSS_COOLDOWN_MIN", "45"))


def block_rest_of_session() -> bool:
    return os.getenv("SYMBOL_LOSS_COOLDOWN_SESSION", "true").lower() in ("1", "true", "yes")


def record_losing_close(db: DB, symbol: str, pnl: float, strategy_id: str = "") -> None:
    if pnl >= 0:
        return
    sym = symbol.replace("NSE:", "").upper()
    until_ts = int(time.time()) + cooldown_minutes_after_loss() * 60
    if block_rest_of_session():
        now = datetime.now(IST)
        close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        if now < close:
            until_ts = max(until_ts, int(close.timestamp()))
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO symbol_session_cooldown(symbol, session_day, until_ts, last_loss_pnl, last_strategy_id, updated_ts)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(symbol, session_day) DO UPDATE SET
              until_ts=excluded.until_ts,
              last_loss_pnl=excluded.last_loss_pnl,
              last_strategy_id=excluded.last_strategy_id,
              updated_ts=excluded.updated_ts
            """,
            (sym, _session_day(), until_ts, pnl, strategy_id, int(time.time())),
        )


def can_reenter_symbol(
    db: DB,
    symbol: str,
    *,
    strategy_id: str,
    confidence: float,
    prior_strategy_id: Optional[str] = None,
) -> tuple[bool, str]:
    sym = symbol.replace("NSE:", "").upper()
    row = db._conn.execute(
        """
        SELECT until_ts, last_strategy_id FROM symbol_session_cooldown
        WHERE symbol=? AND session_day=?
        """,
        (sym, _session_day()),
    ).fetchone()
    if not row:
        return True, "ok"
    until_ts = int(row["until_ts"] or 0)
    if int(time.time()) >= until_ts:
        return True, "ok"
    last_sid = str(row["last_strategy_id"] or "")
    override_conf = float(os.getenv("SYMBOL_COOLDOWN_OVERRIDE_CONF", "0.88"))
    if strategy_id != last_sid and confidence >= override_conf:
        return True, "materially_different_signal"
    wait_min = max(0, (until_ts - int(time.time())) // 60)
    return False, f"symbol_loss_cooldown_{sym}_{wait_min}m"

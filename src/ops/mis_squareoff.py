"""Hard MIS square-off before broker auto-square (~15:10 IST)."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db.database import DB
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.mis_squareoff")


def _squareoff_hour() -> float:
    """Default 15:10 IST = 15 + 10/60."""
    h = os.getenv("MIS_SQUAREOFF_HOUR", "15.167")  # 15:10
    return float(h)


async def run_mis_squareoff_loop(db: DB, publish, interval_sec: float = 30.0) -> None:
    tz = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
    fired_today = ""
    while True:
        try:
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            if now.weekday() < 5 and fired_today != today:
                hour = now.hour + now.minute / 60.0
                if hour >= _squareoff_hour() and hour < 15.5:
                    fired_today = today
                    cur = db._conn.execute(
                        "SELECT symbol, qty, last_price, rail FROM positions WHERE qty > 0"
                    )
                    count = 0
                    for row in cur.fetchall():
                        if str(row["rail"] or "CNC").upper() != "MIS":
                            continue
                        sym = row["symbol"]
                        await publish(
                            MarketEvent(
                                type=EventType.STOP_BREACH,
                                symbol=sym,
                                price=float(row["last_price"]),
                                payload={
                                    "rail": "MIS",
                                    "reason": "hard_squareoff_1510",
                                    "qty": int(row["qty"]),
                                },
                            )
                        )
                        count += 1
                    logger.warning("mis_hard_squareoff", extra={"count": count, "day": today})
        except Exception:
            logger.exception("mis_squareoff_error")
        await asyncio.sleep(interval_sec)

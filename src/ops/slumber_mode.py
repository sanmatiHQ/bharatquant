"""Force slumber — ignore new entry signals for N minutes (tactical override)."""
from __future__ import annotations

import os
import time

from ..db.database import DB

KEY_SLUMBER_UNTIL = "slumber_until_ts"
KEY_SLUMBER_REASON = "slumber_reason"


def enter_slumber(db: DB, minutes: int | None = None, reason: str = "manual_slumber") -> dict:
    mins = minutes or int(os.getenv("SLUMBER_DEFAULT_MINUTES", "60"))
    until = int(time.time()) + mins * 60
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_SLUMBER_UNTIL, str(until)),
        )
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_SLUMBER_REASON, reason),
        )
    return {"ok": True, "until_ts": until, "minutes": mins, "reason": reason}


def clear_slumber(db: DB) -> dict:
    with db.tx() as conn:
        conn.execute("DELETE FROM settings WHERE k IN (?,?)", (KEY_SLUMBER_UNTIL, KEY_SLUMBER_REASON))
    return {"ok": True, "cleared": True}


def slumber_status(db: DB) -> dict:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_SLUMBER_UNTIL,)).fetchone()
    reason_row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_SLUMBER_REASON,)).fetchone()
    now = int(time.time())
    if not row or not str(row["v"]).isdigit():
        return {"active": False, "remaining_sec": 0}
    until = int(row["v"])
    if until <= now:
        return {"active": False, "remaining_sec": 0}
    return {
        "active": True,
        "until_ts": until,
        "remaining_sec": until - now,
        "reason": reason_row["v"] if reason_row else "slumber",
    }


def is_slumbering(db: DB) -> bool:
    return slumber_status(db)["active"]

"""Trading halt — BQ-A6. Persists in SQLite settings."""
from __future__ import annotations

import time
from typing import Optional

_HALT_KEY = "trading_halted"
_REASON_KEY = "halt_reason"
_TS_KEY = "halt_ts"


def set_halt(db, *, reason: str = "manual") -> None:
    ts = str(int(time.time()))
    with db.tx() as conn:
        for k, v in [(_HALT_KEY, "1"), (_REASON_KEY, reason), (_TS_KEY, ts)]:
            conn.execute(
                "INSERT INTO settings(k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (k, v),
            )


def clear_halt(db) -> None:
    with db.tx() as conn:
        for k in (_HALT_KEY, _REASON_KEY, _TS_KEY):
            conn.execute("DELETE FROM settings WHERE k=?", (k,))


def is_halted(db) -> bool:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (_HALT_KEY,)).fetchone()
    return bool(row and row["v"] == "1")


def halt_status(db) -> dict:
    conn = db._conn
    h = conn.execute("SELECT v FROM settings WHERE k=?", (_HALT_KEY,)).fetchone()
    r = conn.execute("SELECT v FROM settings WHERE k=?", (_REASON_KEY,)).fetchone()
    t = conn.execute("SELECT v FROM settings WHERE k=?", (_TS_KEY,)).fetchone()
    return {
        "halted": bool(h and h["v"] == "1"),
        "reason": r["v"] if r else None,
        "halt_ts": int(t["v"]) if t and t["v"].isdigit() else None,
    }


def get_setting(db, key: str, default: Optional[str] = None) -> Optional[str]:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def set_setting(db, key: str, value: str) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (key, value),
        )

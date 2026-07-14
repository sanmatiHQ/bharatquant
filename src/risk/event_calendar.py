"""RBI / expiry / budget event calendar — published MPC dates, not approx placeholders."""
from __future__ import annotations

import calendar
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

from ..db.database import DB

logger = logging.getLogger("bharatquant.calendar")
_TZ = ZoneInfo("Asia/Kolkata")

# RBI MPC meeting dates (published schedule) — extend annually or via RBI_CALENDAR_JSON
_RBI_MPC_BY_YEAR: dict[int, list[tuple[int, int]]] = {
    2025: [(2, 7), (4, 9), (6, 6), (8, 8), (10, 9), (12, 5)],
    2026: [(2, 6), (4, 8), (6, 5), (8, 7), (10, 8), (12, 4)],
}


def _load_rbi_dates(year: int) -> list[date]:
    extra = os.getenv("RBI_CALENDAR_JSON", "")
    if extra and Path(extra).exists():
        try:
            data = json.loads(Path(extra).read_text(encoding="utf-8"))
            rows = data.get(str(year), data.get(year, []))
            return [date(year, int(m), int(d)) for m, d in rows]
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("rbi_calendar_json_invalid", extra={"path": extra})
    raw = _RBI_MPC_BY_YEAR.get(year, [])
    return [date(year, m, d) for m, d in raw]


def _last_thursday(y: int, m: int) -> date:
    last = calendar.monthrange(y, m)[1]
    d = date(y, m, last)
    while d.weekday() != 3:
        d = d.replace(day=d.day - 1)
    return d


def build_quarter_expiry_dates(year: int) -> List[date]:
    months = [3, 6, 9, 12]
    return [_last_thursday(year, m) for m in months]


def seed_calendar_year(db: DB, year: int | None = None) -> int:
    year = year or datetime.now(_TZ).year
    rows = []
    for ed in build_quarter_expiry_dates(year):
        rows.append((ed.isoformat(), "NSE_EXPIRY", f"Monthly expiry {ed}", "high"))
    rows.append((f"{year}-02-01", "BUDGET", "Union Budget window", "high"))
    for mpc in _load_rbi_dates(year):
        rows.append((mpc.isoformat(), "RBI_POLICY", f"RBI MPC {mpc.isoformat()}", "high"))
    with db.tx() as conn:
        for r in rows:
            conn.execute(
                """
                INSERT OR IGNORE INTO calendar_events(event_date, event_type, title, risk_level)
                VALUES (?,?,?,?)
                """,
                r,
            )
    return len(rows)


def today_risk_level(db: DB, today: date | None = None) -> str:
    today = today or datetime.now(_TZ).date()
    cur = db._conn.execute(
        """
        SELECT risk_level FROM calendar_events
        WHERE event_date=? OR event_date LIKE ?
        """,
        (today.isoformat(), f"{today.year}-{today.month:02d}-%"),
    )
    levels = [r["risk_level"] for r in cur.fetchall()]
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low"


def mis_allowed_today(db: DB) -> bool:
    return today_risk_level(db) != "high"

"""RBI / expiry / budget event calendar — risk-down on high-impact days."""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime
from typing import List
from zoneinfo import ZoneInfo

from ..db.database import DB

logger = logging.getLogger("bharatquant.calendar")
_TZ = ZoneInfo("Asia/Kolkata")


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
    rows.append((f"{year}-04-01", "RBI_POLICY", "RBI policy (approx)", "medium"))
    rows.append((f"{year}-06-01", "RBI_POLICY", "RBI policy (approx)", "medium"))
    rows.append((f"{year}-08-01", "RBI_POLICY", "RBI policy (approx)", "medium"))
    rows.append((f"{year}-10-01", "RBI_POLICY", "RBI policy (approx)", "medium"))
    rows.append((f"{year}-12-01", "RBI_POLICY", "RBI policy (approx)", "medium"))
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

"""NSE/BSE session clock — localize US session-timed strategies to IST."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")

NSE_OPEN = time(9, 15)
OPENING_DRIVE_END = time(9, 45)
LUNCH_START = time(12, 0)
LUNCH_END = time(13, 30)
POWER_HOUR_START = time(14, 30)
NSE_CLOSE = time(15, 30)


def ist_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(_IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=_IST)
    return now.astimezone(_IST)


def session_phase(now: datetime | None = None) -> str:
    """pre_open | opening_drive | morning | lunch | afternoon | power_hour | after_close | closed."""
    dt = ist_now(now)
    if dt.weekday() >= 5:
        return "closed"
    t = dt.time()
    if t < NSE_OPEN:
        return "pre_open"
    if t < OPENING_DRIVE_END:
        return "opening_drive"
    if t < LUNCH_START:
        return "morning"
    if t < LUNCH_END:
        return "lunch"
    if t < POWER_HOUR_START:
        return "afternoon"
    if t < NSE_CLOSE:
        return "power_hour"
    return "after_close"


def is_monthly_expiry_day(now: datetime | None = None) -> bool:
    """India F&O monthly expiry — last Thursday of the month."""
    dt = ist_now(now)
    if dt.weekday() != 3:
        return False
    nxt = dt + timedelta(days=7)
    return nxt.month != dt.month


def is_nse_open(now: datetime | None = None) -> bool:
    """NSE cash session 09:15–15:30 IST Mon–Fri (wall clock; not exchange API)."""
    dt = ist_now(now)
    if dt.weekday() >= 5:
        return False
    t = dt.time()
    return NSE_OPEN <= t <= NSE_CLOSE


def minutes_to_close(now: datetime | None = None) -> int:
    dt = ist_now(now)
    if not is_nse_open(dt):
        return 0
    close_dt = dt.replace(hour=15, minute=30, second=0, microsecond=0)
    return max(0, int((close_dt - dt).total_seconds() // 60))


def minutes_from_open(now: datetime | None = None) -> int:
    dt = ist_now(now)
    if dt.weekday() >= 5:
        return 0
    open_dt = dt.replace(hour=9, minute=15, second=0, microsecond=0)
    if dt < open_dt:
        return 0
    return max(0, int((dt - open_dt).total_seconds() // 60))


def market_clock_snapshot(now: datetime | None = None, nse_status: str | None = None) -> dict:
    """Single snapshot for context, dashboard, and strategies."""
    dt = ist_now(now)
    return {
        "session_phase": session_phase(dt),
        "market_open": is_nse_open(dt),
        "ist_date": dt.strftime("%Y-%m-%d"),
        "ist_time": dt.strftime("%H:%M:%S"),
        "weekday": dt.weekday(),
        "is_weekend": dt.weekday() >= 5,
        "is_expiry_day": is_monthly_expiry_day(dt),
        "minutes_to_close": minutes_to_close(dt),
        "minutes_from_open": minutes_from_open(dt),
        "nse_status": nse_status or "Unknown",
    }

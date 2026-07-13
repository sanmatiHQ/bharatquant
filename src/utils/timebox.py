"""
IST-aware time helpers and scheduling utilities.
"""
from __future__ import annotations
import datetime as _dt
from dataclasses import dataclass
from typing import Tuple
import pytz

_IST = pytz.timezone("Asia/Kolkata")


def now_ist() -> _dt.datetime:
    """Return current time in IST with tzinfo."""
    return _dt.datetime.now(tz=_IST)


def today_ist() -> _dt.date:
    """Return today's date in IST."""
    return now_ist().date()


def parse_hhmm(s: str) -> Tuple[int, int]:
    """Parse a string like "HH:MM" into (hour, minute)."""
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid HH:MM: {s}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Invalid hour/minute: {s}")
    return h, m


def next_time_today(hh: int, mm: int) -> _dt.datetime:
    """Return next occurrence of HH:MM today in IST; if past, return tomorrow's HH:MM."""
    now = now_ist()
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + _dt.timedelta(days=1)
    return candidate


def is_market_open(ts: _dt.datetime | None = None) -> bool:
    """Return True if within NSE cash market hours (09:15–15:30 IST) Monday–Friday."""
    from ..strategies.market_session import is_nse_open, ist_now

    if ts is None:
        return is_nse_open()
    if ts.tzinfo is None:
        ts = _IST.localize(ts)
    return is_nse_open(ts)

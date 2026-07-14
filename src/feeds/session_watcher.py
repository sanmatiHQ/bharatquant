"""NSE market status poller → session lifecycle events (not trading cron)."""
from __future__ import annotations

import logging
from typing import Callable, Optional

import httpx

from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.session")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}

_STATUS_MAP = {
    "Pre-Open": EventType.SESSION_PRE_OPEN,
    "Pre-open": EventType.SESSION_PRE_OPEN,
    "Pre Open": EventType.SESSION_PRE_OPEN,
    "Open": EventType.SESSION_OPEN,
    "Close": EventType.SESSION_CLOSE,
    "Closed": EventType.SESSION_CLOSE,
}


def _phase_from_status(status: str):
    from ..ops.session_state import normalize_nse_status, set_session_phase

    phase = normalize_nse_status(status)
    set_session_phase(phase)
    if phase == "PRE_OPEN":
        return EventType.SESSION_PRE_OPEN
    if phase == "OPEN":
        return EventType.SESSION_OPEN
    if phase == "CLOSED":
        return EventType.SESSION_CLOSE
    return _STATUS_MAP.get(status)


async def fetch_nse_status() -> str:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        await client.get("https://www.nseindia.com", headers=NSE_HEADERS)
        r = await client.get(
            "https://www.nseindia.com/api/marketStatus",
            headers=NSE_HEADERS,
        )
        r.raise_for_status()
        data = r.json()
    markets = data if isinstance(data, list) else data.get("marketState", [])
    for m in markets:
        if str(m.get("market", "")).lower() in ("capital market", "cm"):
            return str(m.get("marketStatus", "Unknown"))
    return "Unknown"


async def poll_session_status(publish: Callable, interval_sec: float = 30.0) -> None:
    import asyncio

    last: Optional[str] = None
    while True:
        try:
            status = await fetch_nse_status()
            if status != last:
                last = status
                et = _phase_from_status(status)
                if et:
                    await publish(MarketEvent(type=et, payload={"nse_status": status}))
                    logger.info("session_change", extra={"status": status})
        except Exception:
            logger.exception("session_poll_error")
        await asyncio.sleep(interval_sec)

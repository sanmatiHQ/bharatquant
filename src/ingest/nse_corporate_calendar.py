"""NSE corporate actions, board meetings, event calendar."""
from __future__ import annotations

import logging
from typing import Callable

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent
from .nse_session import nse_get_json, rows_from_payload

logger = logging.getLogger("bharatquant.ingest.nse_calendar")

_ENDPOINTS = (
    (EventType.CORPORATE_ACTION, "https://www.nseindia.com/api/corporate-actions", {"index": "equities"}),
    (EventType.BOARD_MEETING, "https://www.nseindia.com/api/corporate-board-meetings", {"index": "equities"}),
    (EventType.EVENT_CALENDAR, "https://www.nseindia.com/api/event-calendar", {"index": "equities"}),
)


async def _poll_endpoint(
    publish: Callable,
    db,
    event_type: EventType,
    url: str,
    params: dict,
    seen: set[str],
) -> int:
    from ..data.provenance import record_ingest

    data = await nse_get_json(url, params=params)
    rows = rows_from_payload(data)
    n = 0
    for row in rows:
        sym = str(row.get("symbol") or row.get("sm_symbol") or "")
        key = f"{event_type}:{sym}:{row.get('exDate', row.get('bm_dt', row.get('date', '')))}:{str(row)[:60]}"
        if key in seen:
            continue
        seen.add(key)
        payload = tag_payload(dict(row), source=url, execution_allowed=False)
        if db is not None:
            with db.tx() as conn:
                record_ingest(conn, source=url, event_type=event_type, payload=payload, execution_allowed=False)
        await publish(MarketEvent(type=event_type, symbol=sym, payload=payload))
        n += 1
    return n


async def poll_corporate_calendar(publish: Callable, interval_sec: float = 900.0, db=None) -> None:
    import asyncio

    seen: set[str] = set()
    while True:
        for event_type, url, params in _ENDPOINTS:
            try:
                count = await _poll_endpoint(publish, db, event_type, url, params, seen)
                if count:
                    logger.info("nse_calendar_ingest", extra={"event": str(event_type), "count": count})
            except Exception:
                logger.exception("nse_calendar_poll_error", extra={"event": str(event_type)})
        await asyncio.sleep(interval_sec)

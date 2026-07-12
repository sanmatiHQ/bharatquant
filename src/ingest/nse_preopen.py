"""NSE pre-open market prices — SIGNAL_ONLY."""
from __future__ import annotations

import logging
from typing import Any, Callable, List

import httpx

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.preopen")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


async def fetch_preopen() -> List[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        await client.get("https://www.nseindia.com", headers=NSE_HEADERS)
        r = await client.get(
            "https://www.nseindia.com/api/market-data-pre-open?key=ALL",
            headers=NSE_HEADERS,
        )
        r.raise_for_status()
        data = r.json()
    rows = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out = []
    for block in rows:
        md = block.get("metadata", block)
        if isinstance(md, dict):
            out.append(md)
    return out


async def poll_preopen(publish: Callable, interval_sec: float = 30.0, db=None) -> None:
    import asyncio

    from ..data.provenance import record_ingest

    published_session = ""
    while True:
        try:
            rows = await fetch_preopen()
            if rows:
                session_key = str(rows[0].get("lastUpdateTime", ""))[:10]
                if session_key != published_session:
                    published_session = session_key
                    for row in rows[:500]:
                        sym = str(row.get("symbol", ""))
                        iep = float(row.get("iep", row.get("lastPrice", 0)) or 0)
                        if not sym or iep <= 0:
                            continue
                        payload = tag_payload(
                            {"iep": iep, "change": row.get("change", 0), "pChange": row.get("pChange", 0)},
                            source="nseindia.com/market-data-pre-open",
                            execution_allowed=False,
                        )
                        await publish(
                            MarketEvent(
                                type=EventType.PREOPEN_PRICE,
                                symbol=sym,
                                price=iep,
                                payload=payload,
                            )
                        )
                    if db is not None:
                        with db.tx() as conn:
                            record_ingest(
                                conn,
                                source="nseindia.com/market-data-pre-open",
                                event_type=EventType.PREOPEN_PRICE,
                                payload={"count": len(rows)},
                                execution_allowed=False,
                            )
                    logger.info("preopen_published", extra={"symbols": len(rows)})
        except Exception:
            logger.exception("preopen_poll_error")
        await asyncio.sleep(interval_sec)

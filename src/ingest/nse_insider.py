"""NSE insider trading filings — public API."""
from __future__ import annotations

import logging
from typing import Any, Callable, List

import httpx

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.insider")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


async def fetch_insider_filings() -> List[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        await client.get("https://www.nseindia.com", headers=NSE_HEADERS)
        r = await client.get(
            "https://www.nseindia.com/api/corporates-pit",
            headers=NSE_HEADERS,
            params={"index": "equities"},
        )
        r.raise_for_status()
        data = r.json()
    rows = data if isinstance(data, list) else data.get("data", [])
    return rows if isinstance(rows, list) else []


async def poll_insider(publish: Callable, interval_sec: float = 300.0, db=None) -> None:
    import asyncio

    from ..data.provenance import record_ingest

    seen: set[str] = set()
    while True:
        try:
            for row in await fetch_insider_filings():
                key = f"{row.get('symbol','')}_{row.get('acqfromDt','')}_{row.get('personName','')}"
                if key in seen:
                    continue
                seen.add(key)
                payload = tag_payload(
                    dict(row),
                    source="nseindia.com/corporates-pit",
                    execution_allowed=False,
                )
                sym = str(row.get("symbol", ""))
                await publish(
                    MarketEvent(
                        type=EventType.INSIDER_FILING,
                        symbol=sym,
                        payload=payload,
                    )
                )
                if db is not None:
                    with db.tx() as conn:
                        record_ingest(
                            conn,
                            source="nseindia.com/corporates-pit",
                            event_type=EventType.INSIDER_FILING,
                            payload=payload,
                            execution_allowed=False,
                        )
        except Exception:
            logger.exception("insider_poll_error")
        await asyncio.sleep(interval_sec)

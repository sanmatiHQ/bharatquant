"""NSE bulk/block deals — public endpoints."""
from __future__ import annotations

import logging
from typing import Any, Callable, List

import httpx

from ..data.provenance import record_ingest, tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.nse")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


async def _nse_get(client: httpx.AsyncClient, path: str) -> Any:
    await client.get("https://www.nseindia.com", headers=NSE_HEADERS)
    r = await client.get(f"https://www.nseindia.com{path}", headers=NSE_HEADERS)
    r.raise_for_status()
    return r.json()


async def fetch_bulk_deals() -> List[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        data = await _nse_get(client, "/api/snapshot-capital-market-largedeals")
    rows = data if isinstance(data, list) else data.get("data", data.get("bulk", []))
    if not isinstance(rows, list):
        return []
    return rows


async def poll_bulk_deals(publish: Callable, interval_sec: float = 120.0, db=None) -> None:
    import asyncio

    seen: set[str] = set()
    while True:
        try:
            for row in await fetch_bulk_deals():
                key = f"{row.get('symbol','')}_{row.get('qty','')}_{row.get('date','')}"
                if key in seen:
                    continue
                seen.add(key)
                payload = tag_payload(
                    dict(row),
                    source="nseindia.com/snapshot-capital-market-largedeals",
                    execution_allowed=False,
                )
                if db is not None:
                    with db.tx() as conn:
                        record_ingest(
                            conn,
                            source="nseindia.com/snapshot-capital-market-largedeals",
                            event_type=EventType.BLOCK_DEAL,
                            payload=payload,
                            execution_allowed=False,
                        )
                await publish(
                    MarketEvent(
                        type=EventType.BLOCK_DEAL,
                        symbol=str(row.get("symbol", "")),
                        price=float(row.get("price", 0) or 0),
                        payload=payload,
                    )
                )
        except Exception:
            logger.exception("bulk_deals_poll_error")
        await asyncio.sleep(interval_sec)

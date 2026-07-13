"""NSE bulk/block deals — public endpoints (largedeal API)."""
from __future__ import annotations

import logging
from typing import Any, Callable, List

import httpx

from ..data.provenance import record_ingest, tag_payload
from ..events.types import EventType, MarketEvent
from ..intelligence.institutional_entities import classify_entity

logger = logging.getLogger("bharatquant.ingest.nse")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/market-data/large-deals",
}

_SNAPSHOT_PATH = "/api/snapshot-capital-market-largedeal"
_SOURCE = "nseindia.com/snapshot-capital-market-largedeal"


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["qty"] = float(row.get("qty", row.get("quantity", 0)) or 0)
    out["price"] = float(row.get("price", row.get("watp", row.get("wap", 0)) or 0))
    side = str(row.get("buySell", row.get("side", "")) or "")
    out["buySell"] = side
    return out


async def _fetch_mode(client: httpx.AsyncClient, mode: str) -> List[dict[str, Any]]:
    r = await client.get(
        f"https://www.nseindia.com{_SNAPSHOT_PATH}",
        headers=NSE_HEADERS,
        params={"mode": mode},
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        return []
    key = {
        "bulk_deals": "BULK_DEALS_DATA",
        "block_deals": "BLOCK_DEALS_DATA",
        "short_deals": "SHORT_DEALS_DATA",
    }.get(mode, "BULK_DEALS_DATA")
    rows = data.get(key) or []
    if not isinstance(rows, list):
        return []
    return [_normalize_row(dict(x)) for x in rows]


async def fetch_bulk_deals() -> List[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        await client.get("https://www.nseindia.com", headers=NSE_HEADERS)
        bulk = await _fetch_mode(client, "bulk_deals")
        block = await _fetch_mode(client, "block_deals")
    return bulk + block


async def _emit_bulk_rows(rows: list[dict], publish: Callable, db=None, seen: set[str] | None = None) -> int:
    seen = seen if seen is not None else set()
    n = 0
    for row in rows:
        key = f"{row.get('symbol','')}_{row.get('qty','')}_{row.get('date','')}_{row.get('clientName','')}"
        if key in seen:
            continue
        seen.add(key)
        client = str(row.get("clientName", row.get("buyer", row.get("seller", ""))) or "")
        entity = classify_entity(client)
        row["entity_class"] = entity
        payload = tag_payload(row, source=_SOURCE, execution_allowed=False)
        if db is not None:
            with db.tx() as conn:
                record_ingest(
                    conn,
                    source=_SOURCE,
                    event_type=EventType.BLOCK_DEAL,
                    payload=payload,
                    execution_allowed=False,
                )
                if entity == "mf" and float(row.get("qty", 0) or 0) >= 25_000:
                    record_ingest(
                        conn,
                        source=_SOURCE,
                        event_type=EventType.MF_HOLDING_UPDATE,
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
        if entity == "mf":
            await publish(
                MarketEvent(
                    type=EventType.MF_HOLDING_UPDATE,
                    symbol=str(row.get("symbol", "")),
                    price=float(row.get("price", 0) or 0),
                    payload=payload,
                )
            )
        n += 1
    return n


async def run_bulk_burst_once(publish: Callable, db=None) -> int:
    """One-shot bulk/block fetch — scheduled at NSE publication windows."""
    rows = await fetch_bulk_deals()
    return await _emit_bulk_rows(rows, publish, db=db)


async def poll_bulk_deals(publish: Callable, interval_sec: float = 120.0, db=None) -> None:
    import asyncio

    seen: set[str] = set()
    while True:
        try:
            rows = await fetch_bulk_deals()
            await _emit_bulk_rows(rows, publish, db=db, seen=seen)
        except Exception:
            logger.exception("bulk_deals_poll_error")
        await asyncio.sleep(interval_sec)

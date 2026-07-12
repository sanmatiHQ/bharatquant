"""NSE delivery percentage — supplemental."""
from __future__ import annotations

import logging
import time
from typing import Callable

import httpx

from ..data.provenance import record_ingest, tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.delivery")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


async def fetch_delivery() -> list[dict]:
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        await client.get("https://www.nseindia.com", headers=NSE_HEADERS)
        r = await client.get(
            "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O",
            headers=NSE_HEADERS,
        )
        r.raise_for_status()
        data = r.json()
    return data.get("data", []) if isinstance(data, dict) else []


async def poll_delivery(publish: Callable, interval_sec: float = 3600.0, db=None) -> None:
    import asyncio

    last_date = ""
    while True:
        try:
            rows = await fetch_delivery()
            for row in rows:
                sym = str(row.get("symbol", ""))
                dp = float(row.get("deliveryToTradedQuantity", row.get("deliveryPerc", 0)) or 0)
                td = str(row.get("date", time.strftime("%Y-%m-%d")))
                if not sym:
                    continue
                if db is not None:
                    with db.tx() as conn:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO delivery_pct(symbol, trade_date, delivery_pct)
                            VALUES (?,?,?)
                            """,
                            (sym, td, dp),
                        )
                if td != last_date:
                    payload = tag_payload({"symbol": sym, "delivery_pct": dp}, source="nse.delivery", execution_allowed=False)
                    await publish(MarketEvent(type=EventType.VOLUME_ANOMALY, symbol=sym, payload=payload))
            last_date = time.strftime("%Y-%m-%d")
            if db is not None:
                with db.tx() as conn:
                    record_ingest(
                        conn,
                        source="nse.delivery",
                        event_type=EventType.VOLUME_ANOMALY,
                        payload={"count": len(rows)},
                        execution_allowed=False,
                    )
        except Exception:
            logger.exception("delivery_poll_error")
        await asyncio.sleep(interval_sec)

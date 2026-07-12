"""NSE corporate announcements RSS."""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Callable

import httpx

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.corp_rss")

RSS_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"


async def fetch_corp_announcements() -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
        "Referer": "https://www.nseindia.com/",
    }
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        await client.get("https://www.nseindia.com", headers=headers)
        r = await client.get(RSS_URL, headers=headers)
        r.raise_for_status()
        data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


async def poll_corp_rss(publish: Callable, interval_sec: float = 600.0, db=None) -> None:
    import asyncio

    from ..data.provenance import record_ingest

    seen: set[str] = set()
    while True:
        try:
            for row in await fetch_corp_announcements():
                key = f"{row.get('symbol','')}_{row.get('an_dt','')}_{row.get('desc','')[:40]}"
                if key in seen:
                    continue
                seen.add(key)
                sym = str(row.get("symbol", ""))
                payload = tag_payload(dict(row), source="nse.corp_announcements", execution_allowed=False)
                await publish(
                    MarketEvent(
                        type=EventType.NEWS_ALERT,
                        symbol=sym,
                        payload=payload,
                    )
                )
            if db is not None:
                with db.tx() as conn:
                    record_ingest(
                        conn,
                        source="nse.corp",
                        event_type=EventType.NEWS_ALERT,
                        payload={"seen": len(seen)},
                        execution_allowed=False,
                    )
        except Exception:
            logger.exception("corp_rss_poll_error")
        await asyncio.sleep(interval_sec)

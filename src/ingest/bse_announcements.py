"""BSE corporate announcements cross-feed."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.bse")

_TZ = ZoneInfo("Asia/Kolkata")
_BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.bseindia.com/",
}
_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"


async def fetch_bse_announcements(days_back: int = 1) -> list[dict]:
    now = datetime.now(_TZ)
    to_dt = now.strftime("%Y%m%d")
    from_dt = (now - timedelta(days=days_back)).strftime("%Y%m%d")
    params = {
        "strCat": "-1",
        "strPrevDate": from_dt,
        "strScrip": "",
        "strSearch": "P",
        "strToDate": to_dt,
        "strType": "C",
    }
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        await client.get("https://www.bseindia.com", headers=_BSE_HEADERS)
        r = await client.get(_API, headers=_BSE_HEADERS, params=params)
        r.raise_for_status()
        data = r.json()
    if isinstance(data, list):
        return data
    return data.get("Table", data.get("data", [])) or []


async def poll_bse_announcements(publish: Callable, interval_sec: float = 900.0, db=None) -> None:
    import asyncio

    from ..data.provenance import record_ingest

    seen: set[str] = set()
    while True:
        try:
            for row in await fetch_bse_announcements():
                scrip = str(row.get("SCRIP_CD") or row.get("scripcode") or "")
                headline = str(row.get("HEADLINE") or row.get("NEWSSUB") or "")[:80]
                key = f"{scrip}_{row.get('NEWS_DT', row.get('DissemDT', ''))}_{headline}"
                if key in seen:
                    continue
                seen.add(key)
                sym = str(row.get("SLONGNAME") or row.get("scrip_cd") or scrip)
                payload = tag_payload(dict(row), source="bse.AnnGetData", execution_allowed=False)
                if db is not None:
                    with db.tx() as conn:
                        record_ingest(
                            conn,
                            source="bse.AnnGetData",
                            event_type=EventType.BSE_ANNOUNCEMENT,
                            payload=payload,
                            execution_allowed=False,
                        )
                await publish(
                    MarketEvent(
                        type=EventType.BSE_ANNOUNCEMENT,
                        symbol=sym,
                        payload=payload,
                    )
                )
        except Exception:
            logger.exception("bse_announcements_poll_error")
        await asyncio.sleep(interval_sec)

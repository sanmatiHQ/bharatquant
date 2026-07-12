"""FII/DII from public JSON API — publishes FII_DII_UPDATE event."""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import httpx

from ..data.provenance import record_ingest, tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.fii_dii")

FII_DII_URL = "https://fii-diidata.mrchartist.com/api/data"
SOURCE = "fii_diidata.mrchartist.com"


async def fetch_fii_dii() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(FII_DII_URL)
        r.raise_for_status()
        data = r.json()
    if not data or "fii_net" not in data and "fn" not in data:
        raise RuntimeError("FII/DII API returned empty payload")
    return {
        "fii_net": float(data.get("fii_net", data.get("fn", 0))),
        "dii_net": float(data.get("dii_net", data.get("dn", 0))),
        "date": data.get("date", data.get("d", "")),
        "pcr": float(data.get("pcr", 0) or 0),
    }


async def poll_fii_dii(publish: Callable[[MarketEvent], Any], interval_sec: float = 300.0, db=None) -> None:
    """Poll when API may update — not fixed 08:45 clock."""
    import asyncio

    last_date = ""
    while True:
        try:
            row = await fetch_fii_dii()
            d = str(row.get("date", ""))
            if d != last_date:
                last_date = d
                payload = tag_payload(row, source=SOURCE, execution_allowed=False)
                ev = MarketEvent(type=EventType.FII_DII_UPDATE, payload=payload)
                await publish(ev)
                if db is not None:
                    with db.tx() as conn:
                        record_ingest(
                            conn,
                            source=SOURCE,
                            event_type=EventType.FII_DII_UPDATE,
                            payload=payload,
                            execution_allowed=False,
                        )
                logger.info("fii_dii_published", extra=row)
        except Exception:
            logger.exception("fii_dii_poll_error")
        await asyncio.sleep(interval_sec)

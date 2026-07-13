"""NSE F&O participant-wise OI CSV — retail vs FII positioning."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent
from .nse_session import NSE_HEADERS

logger = logging.getLogger("bharatquant.ingest.participant_oi")

_TZ = ZoneInfo("Asia/Kolkata")
_ARCHIVE = "https://archives.nseindia.com/content/nsccl/fao_participant_oi_{ddmmyyyy}.csv"


def _parse_participant_csv(text: str) -> list[dict]:
    rows: list[dict] = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 3:
            continue
        client = str(row[0]).strip().lower()
        if client in ("client type", "client", "fii", "dii", "pro", "total"):
            try:
                long_c = float(str(row[1]).replace(",", "") or 0)
                short_c = float(str(row[2]).replace(",", "") or 0)
            except ValueError:
                continue
            rows.append({"client_type": client, "long": long_c, "short": short_c, "net": long_c - short_c})
    return rows


async def fetch_participant_oi(trade_date: datetime | None = None) -> list[dict]:
    dt = trade_date or datetime.now(_TZ)
    for offset in range(0, 5):
        d = dt - timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        url = _ARCHIVE.format(ddmmyyyy=d.strftime("%d%m%Y"))
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            await client.get("https://www.nseindia.com", headers=NSE_HEADERS)
            r = await client.get(url, headers={**NSE_HEADERS, "Referer": "https://www.nseindia.com/"})
            if r.status_code == 200 and "Client Type" in r.text:
                return _parse_participant_csv(r.text)
    return []


async def poll_participant_oi(publish: Callable, interval_sec: float = 3600.0, db=None) -> None:
    import asyncio

    from ..data.provenance import record_ingest

    last_key = ""
    while True:
        try:
            rows = await fetch_participant_oi()
            if not rows:
                await asyncio.sleep(interval_sec)
                continue
            key = str(rows[0]) + str(len(rows))
            if key == last_key:
                await asyncio.sleep(interval_sec)
                continue
            last_key = key
            by_type = {r["client_type"]: r for r in rows}
            payload = tag_payload(
                {
                    "participants": rows,
                    "client_net": by_type.get("client", {}).get("net", 0),
                    "fii_net": by_type.get("fii", {}).get("net", 0),
                    "dii_net": by_type.get("dii", {}).get("net", 0),
                    "pro_net": by_type.get("pro", {}).get("net", 0),
                },
                source="nse.fao_participant_oi",
                execution_allowed=False,
            )
            if db is not None:
                with db.tx() as conn:
                    record_ingest(
                        conn,
                        source="nse.fao_participant_oi",
                        event_type=EventType.PARTICIPANT_OI_UPDATE,
                        payload=payload,
                        execution_allowed=False,
                    )
            await publish(MarketEvent(type=EventType.PARTICIPANT_OI_UPDATE, payload=payload))
            logger.info("participant_oi_ingest", extra={"rows": len(rows)})
        except Exception:
            logger.exception("participant_oi_poll_error")
        await asyncio.sleep(interval_sec)

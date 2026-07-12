"""Screener.in fundamentals cache — ROE/PE for quality factor."""
from __future__ import annotations

import logging
import re
import time
from typing import Callable, Optional

import httpx

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.screener")

SCREENER_URL = "https://www.screener.in/company/{symbol}/"


async def fetch_fundamentals(symbol: str) -> Optional[dict]:
    sym = symbol.replace("NSE:", "").strip()
    if not sym:
        return None
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)"}
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        r = await client.get(SCREENER_URL.format(symbol=sym), headers=headers)
        if r.status_code != 200:
            return None
        html = r.text
    roe_m = re.search(r"Return on equity[^%]*?([\d.]+)\s*%", html, re.I)
    pe_m = re.search(r"Stock P/E[^<]*?([\d.]+)", html, re.I)
    mcap_m = re.search(r"Market Cap[^₹]*?₹\s*([\d,.]+)\s*Cr", html, re.I)
    return {
        "symbol": sym,
        "roe": float(roe_m.group(1)) if roe_m else None,
        "pe": float(pe_m.group(1)) if pe_m else None,
        "market_cap_cr": float(mcap_m.group(1).replace(",", "")) if mcap_m else None,
    }


async def poll_screener_batch(symbols: list[str], publish: Callable, db=None) -> int:
    n = 0
    for sym in symbols[:20]:
        try:
            row = await fetch_fundamentals(sym)
            if not row:
                continue
            ts = int(time.time())
            if db is not None:
                with db.tx() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO fundamentals_cache(symbol, roe, pe, market_cap_cr, updated_ts)
                        VALUES (?,?,?,?,?)
                        """,
                        (row["symbol"], row.get("roe"), row.get("pe"), row.get("market_cap_cr"), ts),
                    )
            payload = tag_payload(row, source="screener.in", execution_allowed=False)
            await publish(MarketEvent(type=EventType.NEWS_ALERT, symbol=row["symbol"], payload=payload))
            n += 1
        except Exception:
            logger.exception("screener_fetch_error", extra={"symbol": sym})
    return n


async def poll_screener_loop(publish: Callable, symbols: list[str], interval_sec: float = 86400.0, db=None) -> None:
    import asyncio

    while True:
        await poll_screener_batch(symbols, publish, db=db)
        await asyncio.sleep(interval_sec)

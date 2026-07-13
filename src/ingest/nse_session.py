"""Shared NSE cookie handshake for ingest pollers."""
from __future__ import annotations

import httpx

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


async def nse_get_json(url: str, *, params: dict | None = None, timeout: float = 25.0) -> list | dict:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        await client.get("https://www.nseindia.com", headers=NSE_HEADERS)
        r = await client.get(url, headers=NSE_HEADERS, params=params or {})
        r.raise_for_status()
        return r.json()


def rows_from_payload(data: list | dict) -> list[dict]:
    if isinstance(data, list):
        return data
    rows = data.get("data", [])
    return rows if isinstance(rows, list) else []

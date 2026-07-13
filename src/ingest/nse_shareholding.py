"""NSE quarterly shareholding pattern — promoter/public % via shareholdings-master (open data)."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, List

import httpx

from ..data.provenance import record_ingest, tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.shareholding")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
}


def _float_pct(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except ValueError:
        return None


def parse_shareholding_master(rows: list[Any], symbol: str) -> dict[str, Any] | None:
    """Parse `corporate-share-holdings-master` list — latest quarter + QoQ deltas."""
    if not isinstance(rows, list) or not rows:
        return None
    latest = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    if not isinstance(latest, dict):
        return None

    sym = str(latest.get("symbol", symbol)).replace("NSE:", "")
    as_of = str(latest.get("date", latest.get("submissionDate", "")) or "")
    promoter = _float_pct(latest.get("pr_and_prgrp"))
    public = _float_pct(latest.get("public_val"))
    employee = _float_pct(latest.get("employeeTrusts"))
    inst_proxy = round(public - employee, 3) if public is not None and employee is not None else public

    deltas: dict[str, float] = {}
    if prev and isinstance(prev, dict):
        for key, field in (("promoter_pct", "pr_and_prgrp"), ("public_pct", "public_val")):
            cur = _float_pct(latest.get(field))
            old = _float_pct(prev.get(field))
            if cur is not None and old is not None:
                deltas[key] = round(cur - old, 3)
        if "public_pct" in deltas:
            deltas["institutional_pct"] = deltas["public_pct"]

    return {
        "symbol": sym,
        "as_of_date": as_of,
        "promoter_pct": promoter,
        "public_pct": public,
        "mf_pct": inst_proxy,
        "fii_pct": None,
        "dii_pct": None,
        "employee_trusts_pct": employee,
        "deltas": deltas,
        "record_id": latest.get("recordId"),
        "quarters_available": len(rows),
        "source_api": "corporate-share-holdings-master",
    }


async def fetch_shareholding(symbol: str) -> dict[str, Any] | None:
    sym = symbol.replace("NSE:", "").upper()
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        await client.get("https://www.nseindia.com", headers=NSE_HEADERS)
        r = await client.get(
            "https://www.nseindia.com/api/corporate-share-holdings-master",
            headers=NSE_HEADERS,
            params={"index": "equities", "symbol": sym},
        )
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, list):
        return None
    return parse_shareholding_master(data, sym)


def _prior_snapshot(db, symbol: str) -> dict | None:
    row = db._conn.execute(
        """
        SELECT * FROM shareholding_snapshots
        WHERE symbol=? ORDER BY ts DESC LIMIT 1
        """,
        (symbol.replace("NSE:", ""),),
    ).fetchone()
    return dict(row) if row else None


def _persist_snapshot(db, snap: dict[str, Any], raw: dict) -> None:
    sym = snap["symbol"]
    as_of = snap.get("as_of_date") or time.strftime("%Y-%m-%d")
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO shareholding_snapshots(
              symbol, as_of_date, promoter_pct, fii_pct, dii_pct, mf_pct, public_pct, payload_json, ts
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol, as_of_date) DO UPDATE SET
              promoter_pct=excluded.promoter_pct,
              fii_pct=excluded.fii_pct,
              dii_pct=excluded.dii_pct,
              mf_pct=excluded.mf_pct,
              public_pct=excluded.public_pct,
              payload_json=excluded.payload_json,
              ts=excluded.ts
            """,
            (
                sym,
                as_of,
                snap.get("promoter_pct"),
                snap.get("fii_pct"),
                snap.get("dii_pct"),
                snap.get("mf_pct"),
                snap.get("public_pct"),
                json.dumps(raw),
                int(time.time()),
            ),
        )


async def poll_shareholding(
    publish: Callable,
    db,
    symbols: List[str] | None = None,
    interval_sec: float = 86400.0,
) -> None:
    import asyncio

    from ..data.instruments import load_watchlist_symbols

    while True:
        try:
            watch = symbols or load_watchlist_symbols(db) or [
                "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
            ]
            for sym in watch[:40]:
                parsed = await fetch_shareholding(sym)
                if not parsed:
                    await asyncio.sleep(0.35)
                    continue
                deltas = dict(parsed.get("deltas") or {})
                prior = _prior_snapshot(db, parsed["symbol"])
                if prior:
                    for fld in ("promoter_pct", "public_pct", "mf_pct"):
                        cur = parsed.get(fld)
                        old = prior.get(fld)
                        if cur is not None and old is not None:
                            deltas.setdefault(fld, round(float(cur) - float(old), 3))

                payload = tag_payload(
                    {**parsed, "deltas": deltas},
                    source="nseindia.com/corporate-share-holdings-master",
                    execution_allowed=False,
                )
                _persist_snapshot(db, parsed, payload)
                with db.tx() as conn:
                    record_ingest(
                        conn,
                        source="nseindia.com/corporate-share-holdings-master",
                        event_type=EventType.SHAREHOLDING_UPDATE,
                        payload=payload,
                        execution_allowed=False,
                    )
                await publish(
                    MarketEvent(
                        type=EventType.SHAREHOLDING_UPDATE,
                        symbol=parsed["symbol"],
                        payload=payload,
                    )
                )
                await asyncio.sleep(0.4)
        except Exception:
            logger.exception("shareholding_poll_error")
        await asyncio.sleep(interval_sec)

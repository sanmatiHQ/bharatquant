"""NIFTY index futures open-interest tracking."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from ..data.provenance import record_ingest, tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.futures_oi")


def _fetch_nifty_fut_oi() -> dict:
    from kiteconnect import KiteConnect
    from ..feeds.kite_ticker import load_access_token

    api_key, token = load_access_token()
    k = KiteConnect(api_key=api_key)
    k.set_access_token(token)
    inst = k.instruments("NFO")
    nifty_fut = sorted(
        [i for i in inst if i.get("name") == "NIFTY" and i.get("instrument_type") == "FUT"],
        key=lambda x: x["expiry"],
    )
    if not nifty_fut:
        raise RuntimeError("no_nifty_futures")
    front = nifty_fut[0]
    key = f"NFO:{front['tradingsymbol']}"
    q = k.quote([key])[key]
    oi = float(q.get("oi", 0) or 0)
    oi_day_high = float(q.get("oi_day_high", oi) or oi)
    oi_day_low = float(q.get("oi_day_low", oi) or oi)
    mid = (oi_day_high + oi_day_low) / 2 if oi_day_high > 0 else oi
    chg_pct = ((oi - mid) / mid * 100.0) if mid > 0 else 0.0
    return {
        "symbol": "NIFTY_FUT",
        "oi": oi,
        "oi_change_pct": chg_pct,
        "tradingsymbol": front["tradingsymbol"],
    }


async def poll_futures_oi(publish: Callable, db=None, interval_sec: float = 300.0) -> None:
    last_oi = 0.0
    while True:
        try:
            data = await asyncio.to_thread(_fetch_nifty_fut_oi)
            oi = float(data["oi"])
            if last_oi > 0:
                data["oi_change_pct"] = (oi - last_oi) / last_oi * 100.0
            last_oi = oi
            ts = int(time.time())
            if db is not None:
                with db.tx() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO futures_oi(symbol, ts, oi, oi_change_pct)
                        VALUES (?,?,?,?)
                        """,
                        ("NIFTY_FUT", ts, oi, float(data["oi_change_pct"])),
                    )
                    record_ingest(
                        conn,
                        source="kite.futures_oi",
                        event_type=EventType.FUTURES_OI_UPDATE,
                        payload=data,
                        execution_allowed=False,
                    )
            payload = tag_payload(data, source="kite.futures_oi", execution_allowed=False)
            await publish(MarketEvent(type=EventType.FUTURES_OI_UPDATE, symbol="NIFTY_FUT", payload=payload))
            logger.info("futures_oi_published", extra={"oi": oi, "chg_pct": data["oi_change_pct"]})
        except Exception:
            logger.exception("futures_oi_poll_error")
        await asyncio.sleep(interval_sec)

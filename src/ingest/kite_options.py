"""Kite option chain + IV — publishes IV_UPDATE."""
from __future__ import annotations

import logging
import os
import time
from typing import Callable, Optional

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.options")


def _load_kite():
    from kiteconnect import KiteConnect
    from ..feeds.kite_ticker import load_access_token

    api_key, token = load_access_token()
    k = KiteConnect(api_key=api_key)
    k.set_access_token(token)
    return k


async def fetch_nifty_iv(db=None) -> Optional[dict]:
    try:
        kite = _load_kite()
    except Exception:
        logger.warning("options_skipped_no_kite")
        return None
    import asyncio

    def _fetch():
        chain = kite.instruments("NFO")
        nifty_opts = [i for i in chain if i.get("name") == "NIFTY" and i.get("instrument_type") in ("CE", "PE")]
        if not nifty_opts:
            return None
        tokens = [i["instrument_token"] for i in nifty_opts[:40]]
        quotes = kite.quote([f"NFO:{i['tradingsymbol']}" for i in nifty_opts[:40]])
        ivs = []
        ts = int(time.time())
        if db is not None:
            with db.tx() as conn:
                for inst in nifty_opts[:40]:
                    key = f"NFO:{inst['tradingsymbol']}"
                    q = quotes.get(key, {})
                    greeks = q.get("greeks", {}) or {}
                    iv = float(greeks.get("iv", 0) or 0)
                    ltp = float(q.get("last_price", 0) or 0)
                    if iv > 0:
                        ivs.append(iv)
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO option_iv(symbol, strike, option_type, iv, ltp, ts)
                            VALUES (?,?,?,?,?,?)
                            """,
                            ("NIFTY", float(inst.get("strike", 0)), inst.get("instrument_type", "CE"), iv, ltp, ts),
                        )
        avg_iv = sum(ivs) / len(ivs) if ivs else 0.0
        return {"vix": avg_iv, "india_vix": avg_iv, "chain_size": len(ivs)}

    return await asyncio.to_thread(_fetch)


async def poll_option_iv(publish: Callable, interval_sec: float = 300.0, db=None) -> None:
    import asyncio

    while True:
        try:
            row = await fetch_nifty_iv(db=db)
            if row and row.get("vix", 0) > 0:
                payload = tag_payload(row, source="kite.nfo_chain", execution_allowed=False)
                await publish(MarketEvent(type=EventType.IV_UPDATE, payload=payload))
        except Exception:
            logger.exception("option_iv_poll_error")
        await asyncio.sleep(interval_sec)

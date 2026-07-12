"""Global macro poll — US futures, crude, USDINR for regime."""
from __future__ import annotations

import logging
from typing import Callable

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.macro")

try:
    import yfinance as yf
except ImportError:
    yf = None


SYMBOLS = {
    "us_sp": "ES=F",
    "crude": "CL=F",
    "usd_inr": "USDINR=X",
    "india_vix": "^INDIAVIX",
}
MACRO_SOURCE = "yfinance_macro_signal"


def _fetch_macro() -> dict[str, float]:
    if yf is None:
        raise RuntimeError("yfinance not installed")
    out: dict[str, float] = {}
    for k, sym in SYMBOLS.items():
        h = yf.Ticker(sym).history(period="5d", interval="1d")
        if h is None or len(h) < 2:
            continue
        c0, c1 = float(h["Close"].iloc[-2]), float(h["Close"].iloc[-1])
        out[k] = (c1 - c0) / c0 * 100.0 if c0 else 0.0
    if not out:
        raise RuntimeError("macro fetch empty")
    return out


async def poll_global_macro(publish: Callable, interval_sec: float = 300.0) -> None:
    import asyncio

    while True:
        try:
            data = _fetch_macro()
            payload = tag_payload(data, source=MACRO_SOURCE, execution_allowed=False)
            await publish(
                MarketEvent(type=EventType.GIFT_SESSION_CHANGE, payload=payload)
            )
            if "india_vix" in data:
                await publish(
                    MarketEvent(
                        type=EventType.IV_UPDATE,
                        payload=tag_payload(
                            {"vix": abs(data["india_vix"]), "india_vix": abs(data["india_vix"])},
                            source=MACRO_SOURCE,
                            execution_allowed=False,
                        ),
                    )
                )
        except Exception:
            logger.exception("macro_poll_error")
        await asyncio.sleep(interval_sec)

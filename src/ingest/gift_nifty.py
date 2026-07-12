"""GIFT Nifty overnight bias — SIGNAL ONLY, never execution price."""
from __future__ import annotations

import logging
from typing import Callable

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.gift")

# Explicit: this feed must not be used for order pricing (see data_policy.py)
SIGNAL_ONLY_SOURCE = "yfinance^NSEI_PROXY"

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore


def _gift_change_pct() -> float:
    if yf is None:
        raise RuntimeError("yfinance not installed")
    t = yf.Ticker("^NSEI")
    hist = t.history(period="5d", interval="1d")
    if hist is None or len(hist) < 2:
        raise RuntimeError("GIFT proxy: insufficient ^NSEI history — not publishing fake gap")
    prev = float(hist["Close"].iloc[-2])
    last = float(hist["Close"].iloc[-1])
    if prev <= 0 or last <= 0:
        raise RuntimeError("GIFT proxy: invalid close prices")
    return (last - prev) / prev * 100.0


async def poll_gift_proxy(publish: Callable, interval_sec: float = 60.0, db=None) -> None:
    import asyncio

    from ..data.provenance import record_ingest

    last_pct: float | None = None
    while True:
        try:
            pct = _gift_change_pct()
            if last_pct is None or abs(pct - last_pct) > 0.05:
                last_pct = pct
                payload = tag_payload(
                    {"change_pct": pct},
                    source=SIGNAL_ONLY_SOURCE,
                    execution_allowed=False,
                )
                await publish(
                    MarketEvent(
                        type=EventType.GIFT_TICK,
                        symbol="GIFT_PROXY",
                        price=0.0,
                        payload=payload,
                    )
                )
                if db is not None:
                    with db.tx() as conn:
                        record_ingest(
                            conn,
                            source=SIGNAL_ONLY_SOURCE,
                            event_type=EventType.GIFT_TICK,
                            payload=payload,
                            execution_allowed=False,
                        )
        except Exception:
            logger.exception("gift_poll_error_no_fake_publish")
        await asyncio.sleep(interval_sec)

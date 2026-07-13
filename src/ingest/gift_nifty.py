"""GIFT Nifty overnight bias — real NSE IX data via marketStatus (SIGNAL ONLY)."""
from __future__ import annotations

import logging
from typing import Callable

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent
from .market_feed_client import fetch_nse_market_status

logger = logging.getLogger("bharatquant.ingest.gift")

SIGNAL_ONLY_SOURCE = "nse.marketStatus.giftnifty"


def _gift_change_pct() -> tuple[float, dict]:
    row = fetch_nse_market_status()
    pct = float(row.get("gift_change_pct", 0))
    if row.get("gift_last", 0) <= 0 and pct == 0:
        raise RuntimeError("GIFT Nifty: empty marketStatus payload")
    return pct, row


async def poll_gift_proxy(publish: Callable, interval_sec: float = 60.0, db=None) -> None:
    import asyncio

    from ..data.provenance import record_ingest

    last_pct: float | None = None
    while True:
        try:
            pct, row = _gift_change_pct()
            if last_pct is None or abs(pct - last_pct) > 0.02:
                last_pct = pct
                payload = tag_payload(
                    {
                        "change_pct": pct,
                        "gift_last": row.get("gift_last"),
                        "gift_day_change": row.get("gift_day_change"),
                        "gift_expiry": row.get("gift_expiry"),
                        "gift_timestamp": row.get("gift_timestamp"),
                        "market_cap_cr": row.get("market_cap_cr"),
                    },
                    source=SIGNAL_ONLY_SOURCE,
                    execution_allowed=False,
                )
                await publish(
                    MarketEvent(
                        type=EventType.GIFT_TICK,
                        symbol="GIFT_NIFTY",
                        price=float(row.get("gift_last", 0)),
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
                logger.info("gift_nifty_published", extra={"change_pct": pct, "last": row.get("gift_last")})
        except Exception:
            logger.exception("gift_poll_error")
        await asyncio.sleep(interval_sec)

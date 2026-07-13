"""Global macro poll — US futures, crude, USDINR, India VIX (multi-source)."""
from __future__ import annotations

import logging
from typing import Callable

from ..data.provenance import tag_payload
from ..events.types import EventType, MarketEvent
from .market_feed_client import fetch_global_macro_bundle

logger = logging.getLogger("bharatquant.ingest.macro")

MACRO_SOURCE = "kite+nse+yahoo_chart"


async def poll_global_macro(publish: Callable, interval_sec: float = 300.0, db=None) -> None:
    import asyncio

    from ..data.provenance import record_ingest

    while True:
        try:
            data = fetch_global_macro_bundle()
            payload = tag_payload({**data, "source": MACRO_SOURCE}, source=MACRO_SOURCE, execution_allowed=False)
            await publish(
                MarketEvent(type=EventType.GIFT_SESSION_CHANGE, symbol="MACRO", payload=payload)
            )
            if db is not None:
                with db.tx() as conn:
                    record_ingest(
                        conn,
                        source=MACRO_SOURCE,
                        event_type=EventType.GIFT_SESSION_CHANGE,
                        payload=payload,
                        execution_allowed=False,
                    )
            vix = float(data.get("india_vix", 0))
            if vix > 0:
                iv_payload = tag_payload(
                    {"vix": vix, "india_vix": vix},
                    source=MACRO_SOURCE,
                    execution_allowed=False,
                )
                await publish(MarketEvent(type=EventType.IV_UPDATE, symbol="INDIA VIX", payload=iv_payload))
            logger.info("macro_published", extra={k: round(v, 2) if isinstance(v, float) else v for k, v in data.items() if k != "fetched_ts"})
        except Exception:
            logger.exception("macro_poll_error")
        await asyncio.sleep(interval_sec)

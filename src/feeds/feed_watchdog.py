"""Feed staleness watchdog — publishes FEED_STALE, triggers reconnect."""
from __future__ import annotations

import logging
import os
import time
from typing import Callable, Optional

from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.feed_watchdog")


class FeedWatchdog:
    def __init__(self, publish: Callable, stale_sec: float | None = None) -> None:
        self.publish = publish
        self.stale_sec = stale_sec or float(os.getenv("FEED_STALE_SEC", "5"))
        self._last_tick_ts: float = time.monotonic()
        self._reconnect_cb: Optional[Callable[[], None]] = None

    def on_tick(self, _event: MarketEvent) -> None:
        self._last_tick_ts = time.monotonic()

    def set_reconnect(self, cb: Callable[[], None]) -> None:
        self._reconnect_cb = cb

    async def run_loop(self) -> None:
        import asyncio

        while True:
            await asyncio.sleep(5)
            age = time.monotonic() - self._last_tick_ts
            if age > self.stale_sec:
                logger.warning("feed_stale", extra={"age_sec": age})
                await self.publish(
                    MarketEvent(
                        type=EventType.FEED_STALE,
                        payload={"age_sec": age},
                    )
                )
                if self._reconnect_cb:
                    try:
                        self._reconnect_cb()
                        await self.publish(MarketEvent(type=EventType.FEED_RECONNECT))
                        self._last_tick_ts = time.monotonic()
                    except Exception:
                        logger.exception("feed_reconnect_failed")

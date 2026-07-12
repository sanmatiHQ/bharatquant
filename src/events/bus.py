"""Async pub/sub event bus — core of event-driven trading."""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Awaitable, Callable, DefaultDict, List

from .types import EventType, MarketEvent

EventHandler = Callable[[MarketEvent], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: DefaultDict[EventType, List[EventHandler]] = defaultdict(list)
        self._queue: asyncio.Queue[MarketEvent] = asyncio.Queue()
        self._logger = logging.getLogger("bharatquant.eventbus")
        self._running = False

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def subscribe_many(self, event_types: list[EventType], handler: EventHandler) -> None:
        for et in event_types:
            self.subscribe(et, handler)

    async def publish(self, event: MarketEvent) -> None:
        await self._queue.put(event)

    def publish_nowait(self, event: MarketEvent) -> None:
        self._queue.put_nowait(event)

    async def run(self) -> None:
        """Process events until cancelled."""
        self._running = True
        self._logger.info("eventbus_started")
        while self._running:
            event = await self._queue.get()
            handlers = list(self._handlers.get(event.type, []))
            for handler in handlers:
                try:
                    result = handler(event)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    self._logger.exception(
                        "handler_error",
                        extra={"event_type": event.type, "symbol": event.symbol},
                    )

    def stop(self) -> None:
        self._running = False

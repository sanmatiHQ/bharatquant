"""
Tick/bar recorder — vnpy data_recorder pattern adapted for asyncio EventBus.

Persists TICK and BAR_CLOSE (5m/15m/1d) to SQLite for backtest replay.
"""
from __future__ import annotations

import logging
import time
from typing import List, Tuple

from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.recorder")

TickRow = Tuple[int, str, float, int | None]
BarRow = Tuple[int, str, str, float, float, float, float, int | None]

_BAR_MAP = {
    EventType.BAR_CLOSE_5M: "5m",
    EventType.BAR_CLOSE_15M: "15m",
    EventType.BAR_CLOSE_1D: "1d",
}


class TickRecorder:
    def __init__(self, db, *, flush_every: int = 200) -> None:
        self._db = db
        self._flush_every = flush_every
        self._tick_buf: List[TickRow] = []
        self._bar_buf: List[BarRow] = []

    def _append_bar(self, event: MarketEvent, interval: str) -> None:
        p = event.payload
        self._bar_buf.append(
            (
                event.ts or int(time.time()),
                event.symbol,
                interval,
                float(p.get("open", event.price)),
                float(p.get("high", event.price)),
                float(p.get("low", event.price)),
                float(p.get("close", event.price)),
                int(p["volume"]) if p.get("volume") is not None else None,
            )
        )

    async def on_event(self, event: MarketEvent) -> None:
        if event.type == EventType.TICK and event.symbol and event.price > 0:
            vol = event.payload.get("volume")
            self._tick_buf.append(
                (event.ts or int(time.time()), event.symbol, float(event.price), int(vol) if vol else None)
            )
        elif event.type in _BAR_MAP and event.symbol:
            self._append_bar(event, _BAR_MAP[event.type])
        if len(self._tick_buf) >= self._flush_every:
            self.flush()

    def flush(self) -> None:
        if not self._tick_buf and not self._bar_buf:
            return
        with self._db.tx() as conn:
            if self._tick_buf:
                conn.executemany(
                    "INSERT INTO tick_log(ts, symbol, ltp, volume) VALUES (?,?,?,?)",
                    self._tick_buf,
                )
                n_ticks = len(self._tick_buf)
                self._tick_buf.clear()
            else:
                n_ticks = 0
            if self._bar_buf:
                conn.executemany(
                    """
                    INSERT INTO bar_log(ts, symbol, interval, open, high, low, close, volume)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    self._bar_buf,
                )
                n_bars = len(self._bar_buf)
                self._bar_buf.clear()
            else:
                n_bars = 0
        if n_ticks or n_bars:
            logger.debug("recorder_flush", extra={"ticks": n_ticks, "bars": n_bars})

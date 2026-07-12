"""Aggregate TICK stream into 5m/15m/1d bars + VWAP + momentum features."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Tuple

from ..events.types import EventType, MarketEvent


@dataclass
class _Bar:
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    vwap_num: float = 0.0
    vwap_den: float = 0.0
    start_ts: int = 0


_INTERVALS: Tuple[Tuple[int, EventType], ...] = (
    (300, EventType.BAR_CLOSE_5M),
    (900, EventType.BAR_CLOSE_15M),
    (86400, EventType.BAR_CLOSE_1D),
)


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(-period, 0):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains.append(delta)
        else:
            losses.append(-delta)
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _momentum_features(closes: Deque[float]) -> dict:
    arr = list(closes)
    if len(arr) < 2:
        return {"r1m": 0.0, "r3m": 0.0, "rsi": 50.0}
    r1m = (arr[-1] - arr[-2]) / arr[-2] if arr[-2] else 0.0
    if len(arr) >= 4 and arr[-4]:
        r3m = (arr[-1] - arr[-4]) / arr[-4]
    else:
        r3m = r1m
    return {"r1m": r1m, "r3m": r3m, "rsi": _rsi(arr)}


class BarAggregator:
    def __init__(self, publish: Callable) -> None:
        self.publish = publish
        self._bars: Dict[Tuple[str, int], _Bar] = {}
        self._last_vwap_side: Dict[str, str] = {}
        self._close_hist: Dict[str, Deque[float]] = {}

    async def on_tick(self, event: MarketEvent) -> None:
        sym = event.symbol
        px = event.price
        if not sym or px <= 0:
            return
        vol = float(event.payload.get("raw", {}).get("volume_traded", 0) or 0)
        now = event.ts or int(time.time())
        for bar_sec, ev_type in _INTERVALS:
            key = (sym, bar_sec)
            bar = self._bars.get(key)
            if bar is None or now - bar.start_ts >= bar_sec:
                if bar and bar.close > 0:
                    await self._emit_bar(sym, bar, ev_type)
                bar = _Bar(open=px, high=px, low=px, close=px, start_ts=now)
                self._bars[key] = bar
            bar.high = max(bar.high, px)
            bar.low = min(bar.low, px)
            bar.close = px
            if vol > 0:
                bar.volume += vol
                bar.vwap_num += px * vol
                bar.vwap_den += vol
        bar5 = self._bars.get((sym, 300))
        if bar5:
            vwap = bar5.vwap_num / bar5.vwap_den if bar5.vwap_den else px
            prev = self._last_vwap_side.get(sym)
            side = "above" if px > vwap else "below" if px < vwap else "at"
            if prev and prev != side and side in ("above", "below"):
                await self.publish(
                    MarketEvent(
                        type=EventType.VWAP_CROSS,
                        symbol=sym,
                        price=px,
                        payload={"vwap": vwap, "side": side},
                    )
                )
            self._last_vwap_side[sym] = side

    async def _emit_bar(self, sym: str, bar: _Bar, ev_type: EventType) -> None:
        vwap = bar.vwap_num / bar.vwap_den if bar.vwap_den else bar.close
        hist = self._close_hist.setdefault(sym, deque(maxlen=20))
        hist.append(bar.close)
        mom = _momentum_features(hist) if ev_type == EventType.BAR_CLOSE_5M else {}
        await self.publish(
            MarketEvent(
                type=ev_type,
                symbol=sym,
                price=bar.close,
                payload={
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "vwap": vwap,
                    **mom,
                },
            )
        )

"""Aggregate TICK stream into 5m/15m/1d bars + VWAP + momentum features."""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Tuple

import numpy as np

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


class TickRingBuffer:
    """Pre-allocated rolling LTP windows for vectorized micro features."""

    def __init__(self, capacity: int = 100, n_symbols: int = 512) -> None:
        self.capacity = max(16, capacity)
        self._buf = np.zeros((n_symbols, self.capacity), dtype=np.float64)
        self._pos = np.zeros(n_symbols, dtype=np.int32)
        self._sym_to_slot: dict[str, int] = {}
        self._next_slot = 0

    def push(self, symbol: str, price: float) -> None:
        if price <= 0:
            return
        sym = symbol.replace("NSE:", "")
        slot = self._sym_to_slot.get(sym)
        if slot is None:
            if self._next_slot >= self._buf.shape[0]:
                return
            slot = self._next_slot
            self._next_slot += 1
            self._sym_to_slot[sym] = slot
        idx = int(self._pos[slot] % self.capacity)
        self._buf[slot, idx] = price
        self._pos[slot] += 1

    def window(self, symbol: str) -> np.ndarray:
        sym = symbol.replace("NSE:", "")
        slot = self._sym_to_slot.get(sym)
        if slot is None:
            return np.array([], dtype=np.float64)
        n = min(int(self._pos[slot]), self.capacity)
        if n <= 0:
            return np.array([], dtype=np.float64)
        if n < self.capacity:
            return self._buf[slot, :n].copy()
        start = int(self._pos[slot] % self.capacity)
        if start == 0:
            return self._buf[slot].copy()
        return np.concatenate([self._buf[slot, start:], self._buf[slot, :start]])

    def atr_bps(self, symbol: str, period: int = 14) -> float:
        w = self.window(symbol)
        if len(w) < 2:
            return 0.0
        tail = w[-period:] if len(w) >= period else w
        diffs = np.abs(np.diff(tail))
        return float(diffs.mean() / w[-1] * 10000.0) if w[-1] > 0 else 0.0


_SHARED_RING: TickRingBuffer | None = None


def shared_tick_ring() -> TickRingBuffer:
    """Process-wide ring buffer — bar aggregator + context updater share one instance."""
    global _SHARED_RING
    if _SHARED_RING is None:
        cap = int(os.getenv("TICK_RING_CAPACITY", "100"))
        _SHARED_RING = TickRingBuffer(capacity=cap)
    return _SHARED_RING


def _ema(prev: float, value: float, period: int) -> float:
    if prev <= 0:
        return value
    k = 2.0 / (period + 1)
    return value * k + prev * (1.0 - k)


def _z_score(closes: list[float]) -> float:
    if len(closes) < 5:
        return 0.0
    import statistics

    tail = closes[-20:]
    m = statistics.mean(tail)
    sd = statistics.stdev(tail) if len(tail) >= 2 else 0.0
    if sd <= 0:
        return 0.0
    return (tail[-1] - m) / sd


class BarAggregator:
    def __init__(self, publish: Callable) -> None:
        self.publish = publish
        self._bars: Dict[Tuple[str, int], _Bar] = {}
        self._last_vwap_side: Dict[str, str] = {}
        self._close_hist: Dict[str, Deque[float]] = {}
        self._high_hist: Dict[str, Deque[float]] = {}
        self._low_hist: Dict[str, Deque[float]] = {}
        self._range_hist: Dict[str, Deque[float]] = {}
        self._daily_close_hist: Dict[str, Deque[float]] = {}
        self._ema_fast: Dict[str, float] = {}
        self._ema_slow: Dict[str, float] = {}
        self._vol_hist: Dict[str, Deque[float]] = {}
        cap = int(os.getenv("TICK_RING_CAPACITY", "100"))
        self.tick_ring = shared_tick_ring()

    def _bb_width(self, closes: list[float]) -> float:
        if len(closes) < 5:
            return 1.0
        import statistics

        m = statistics.mean(closes[-20:])
        sd = statistics.stdev(closes[-20:]) if len(closes) >= 2 else 0.0
        if m <= 0:
            return 1.0
        return (4 * sd) / m * 100.0

    def _vol_ratio(self, sym: str, vol: float) -> float:
        hist = self._vol_hist.setdefault(sym, deque(maxlen=20))
        hist.append(vol)
        if len(hist) < 3 or vol <= 0:
            return 1.0
        avg = sum(hist) / len(hist)
        return vol / avg if avg > 0 else 1.0

    async def on_tick(self, event: MarketEvent) -> None:
        sym = event.symbol
        px = event.price
        if not sym or px <= 0:
            return
        self.tick_ring.push(sym, px)
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

    def _bar_features(self, sym: str, bar: _Bar) -> dict:
        """Literature-ready features: Donchian, IBS, NR7, z-score, EMA cross, ret_5d."""
        hist = self._close_hist.setdefault(sym, deque(maxlen=20))
        high_hist = self._high_hist.setdefault(sym, deque(maxlen=20))
        low_hist = self._low_hist.setdefault(sym, deque(maxlen=20))
        range_hist = self._range_hist.setdefault(sym, deque(maxlen=7))
        hist.append(bar.close)
        high_hist.append(bar.high)
        low_hist.append(bar.low)
        bar_range = max(bar.high - bar.low, 0.0)
        range_hist.append(bar_range)
        closes = list(hist)
        highs = list(high_hist)
        lows = list(low_hist)
        ibs = (bar.close - bar.low) / bar_range if bar_range > 0 else 0.5
        z_score = _z_score(closes)
        high_20 = max(highs) if highs else bar.high
        low_20 = min(lows) if lows else bar.low
        nr7 = len(range_hist) >= 7 and bar_range <= min(range_hist) * 1.001
        ema9 = _ema(self._ema_fast.get(sym, 0.0), bar.close, 9)
        ema21 = _ema(self._ema_slow.get(sym, 0.0), bar.close, 21)
        self._ema_fast[sym] = ema9
        self._ema_slow[sym] = ema21
        daily = self._daily_close_hist.get(sym, deque())
        ret_5d = 0.0
        if len(daily) >= 6 and daily[-6] > 0:
            ret_5d = (bar.close - daily[-6]) / daily[-6]
        lower_high = 0
        lower_high_streak = 0
        if len(highs) >= 2 and highs[-1] < highs[-2]:
            lower_high = 1
            streak = 1
            for i in range(len(highs) - 2, 0, -1):
                if highs[i] < highs[i - 1]:
                    streak += 1
                else:
                    break
            lower_high_streak = streak
        near_high_20 = int(high_20 > 0 and bar.close >= high_20 * 0.995)
        return {
            "high_20": high_20,
            "low_20": low_20,
            "ibs": round(ibs, 4),
            "z_score": round(z_score, 4),
            "nr7": int(nr7),
            "ema9": round(ema9, 4),
            "ema21": round(ema21, 4),
            "ema_cross_up": int(ema9 > ema21),
            "ret_5d": round(ret_5d, 6),
            "range_pct": round(bar_range / bar.close * 100, 4) if bar.close > 0 else 0.0,
            "lower_high": lower_high,
            "lower_high_streak": lower_high_streak,
            "near_high_20": near_high_20,
        }

    async def _emit_bar(self, sym: str, bar: _Bar, ev_type: EventType) -> None:
        vwap = bar.vwap_num / bar.vwap_den if bar.vwap_den else bar.close
        if ev_type == EventType.BAR_CLOSE_1D:
            self._daily_close_hist.setdefault(sym, deque(maxlen=8)).append(bar.close)
        mom: dict = {}
        lit: dict = {}
        closes = list(self._close_hist.get(sym, []))
        if ev_type == EventType.BAR_CLOSE_5M:
            lit = self._bar_features(sym, bar)
            mom = _momentum_features(self._close_hist[sym])
            closes = list(self._close_hist[sym])
        bb_w = self._bb_width(closes) if ev_type == EventType.BAR_CLOSE_5M else 0.0
        vol_ratio = self._vol_ratio(sym, bar.volume) if ev_type == EventType.BAR_CLOSE_5M else 1.0
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
                    "bb_width": bb_w,
                    "vol_ratio": vol_ratio,
                    **mom,
                    **lit,
                },
            )
        )

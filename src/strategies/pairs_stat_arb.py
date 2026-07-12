"""Pairs stat arb — spread z-score on correlated names."""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy

# Default pair — configurable via env later
_PAIR = ("RELIANCE", "ONGC")


class PairsStatArbStrategy:
    id = "pairs_stat_arb"
    listens_to = {EventType.BAR_CLOSE_15M, EventType.TICK}

    def __init__(self) -> None:
        self._prices: dict[str, list[float]] = {}

    def _zscore(self, a: list[float], b: list[float]) -> float:
        if len(a) < 30 or len(b) < 30:
            return 0.0
        spread = np.log(np.array(a[-30:])) - np.log(np.array(b[-30:]))
        mu, sd = float(spread.mean()), float(spread.std())
        if sd <= 0:
            return 0.0
        return float((spread[-1] - mu) / sd)

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = event.symbol.replace("NSE:", "")
        if sym not in _PAIR or event.price <= 0:
            return None
        self._prices.setdefault(sym, []).append(event.price)
        if len(self._prices[sym]) > 120:
            self._prices[sym] = self._prices[sym][-120:]
        other = _PAIR[1] if sym == _PAIR[0] else _PAIR[0]
        if other not in self._prices or len(self._prices[other]) < 30:
            return None
        z = self._zscore(self._prices[sym], self._prices[other])
        if z < -2.0:
            return Signal(self.id, sym, "BUY", "MIS", min(0.9, abs(z) / 3), f"pair_z_{z:.2f}")
        if z > 2.0:
            return Signal(self.id, sym, "SELL", "MIS", min(0.9, abs(z) / 3), f"pair_z_{z:.2f}")
        return None

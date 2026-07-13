"""Pairs stat arb — live spread z-score on correlated sector pairs."""
from __future__ import annotations

import os
from typing import Optional, Tuple

import numpy as np

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy

_DEFAULT_PAIR = ("RELIANCE", "ONGC")


def _parse_pairs() -> list[Tuple[str, str]]:
    raw = os.getenv("PAIRS_ARB_LIST", "")
    if not raw:
        return [_DEFAULT_PAIR]
    out = []
    for chunk in raw.split(","):
        parts = chunk.strip().split("/")
        if len(parts) == 2:
            out.append((parts[0].strip(), parts[1].strip()))
    return out or [_DEFAULT_PAIR]


class PairsStatArbStrategy:
    id = "pairs_stat_arb"
    listens_to = {EventType.BAR_CLOSE_5M, EventType.TICK}

    def __init__(self, db=None) -> None:
        self.db = db
        self._prices: dict[str, list[float]] = {}
        self._pairs = _parse_pairs()

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
        if event.price <= 0:
            return None
        pair_hit = None
        for a, b in self._pairs:
            if sym in (a, b):
                pair_hit = (a, b)
                break
        if not pair_hit:
            return None
        self._prices.setdefault(sym, []).append(event.price)
        if len(self._prices[sym]) > 120:
            self._prices[sym] = self._prices[sym][-120:]
        other = pair_hit[1] if sym == pair_hit[0] else pair_hit[0]
        if other not in self._prices or len(self._prices[other]) < 30:
            return None
        z = self._zscore(self._prices[sym], self._prices[other])
        vol_ratio = float((event.payload or {}).get("vol_ratio", 1.0))
        if event.type == EventType.BAR_CLOSE_5M and vol_ratio < 1.2:
            return None
        if z < -2.0:
            return Signal(self.id, sym, "BUY", "MIS", min(0.9, abs(z) / 3), f"pair_z_{z:.2f}")
        if z > 2.0:
            return Signal(self.id, sym, "SELL", "MIS", min(0.9, abs(z) / 3), f"pair_z_{z:.2f}")
        return None

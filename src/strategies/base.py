"""Strategy plugin protocol — register 1..N strategies in config."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from ..events.types import EventType, MarketEvent


@dataclass
class Signal:
    strategy_id: str
    symbol: str
    action: str  # BUY | SELL | HOLD | HEDGE
    rail: str  # CNC | MIS | NRML | OPT
    confidence: float
    reason: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketContext:
    """Mutable session state updated by feeds — not wall-clock schedules."""
    regime: str = "NEUTRAL"
    gift_nifty_change_pct: float = 0.0
    fii_net_cr: float = 0.0
    dii_net_cr: float = 0.0
    india_vix: float = 0.0
    orb_high: dict[str, float] = field(default_factory=dict)
    orb_low: dict[str, float] = field(default_factory=dict)
    session_vwap: dict[str, float] = field(default_factory=dict)
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)


@runtime_checkable
class Strategy(Protocol):
    id: str
    listens_to: set[EventType]

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        ...

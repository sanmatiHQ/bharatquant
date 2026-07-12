"""Strategy unit tests — no live market data."""
from __future__ import annotations

import asyncio

import pytest

from src.events.types import EventType, MarketEvent
from src.strategies.base import MarketContext
from src.strategies.combined_momentum import CombinedMomentumStrategy
from src.strategies.gift_gap import GiftGapStrategy
from src.strategies.registry import StrategyRegistry
from src.strategies.stop_loss_guard import StopLossGuardStrategy


@pytest.mark.asyncio
async def test_combined_momentum_buy():
    s = CombinedMomentumStrategy()
    ctx = MarketContext(fii_net_cr=500)
    ev = MarketEvent(
        type=EventType.BAR_CLOSE_5M,
        symbol="INFY",
        price=1500,
        payload={"r3m": 0.08, "r1m": 0.02, "rsi": 55},
    )
    sig = await s.on_event(ev, ctx)
    assert sig is not None
    assert sig.action == "BUY"


@pytest.mark.asyncio
async def test_gift_gap_up():
    s = GiftGapStrategy()
    ctx = MarketContext()
    await s.on_event(MarketEvent(type=EventType.GIFT_TICK, payload={"change_pct": 0.6}), ctx)
    sig = await s.on_event(MarketEvent(type=EventType.SESSION_OPEN, symbol="NIFTYBEES"), ctx)
    assert sig and sig.action == "BUY"


@pytest.mark.asyncio
async def test_stop_loss_guard():
    s = StopLossGuardStrategy()
    ctx = MarketContext(positions={"INFY": {"avg_price": 100, "stop_loss_pct": 4, "rail": "CNC"}})
    sig = await s.on_event(MarketEvent(type=EventType.TICK, symbol="INFY", price=95), ctx)
    assert sig and sig.action == "SELL"


def test_registry_loads_all():
    reg = StrategyRegistry()
    assert len(reg._strategies) == 17

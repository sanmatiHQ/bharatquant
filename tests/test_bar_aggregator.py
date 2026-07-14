"""Bar aggregator exchange-aligned bucket tests."""
from __future__ import annotations

import pytest

from src.events.types import EventType, MarketEvent
from src.feeds.bar_aggregator import BarAggregator


@pytest.mark.asyncio
async def test_bar_bucket_aligned_not_elapsed_since_first_tick():
    emitted = []

    async def pub(ev: MarketEvent):
        emitted.append(ev)

    agg = BarAggregator(pub)
    base = 1_700_000_000
    await agg.on_tick(MarketEvent(type=EventType.TICK, symbol="INFY", price=100.0, ts=base + 10))
    await agg.on_tick(MarketEvent(type=EventType.TICK, symbol="INFY", price=101.0, ts=base + 50))
    assert len(emitted) == 0
    await agg.on_tick(MarketEvent(type=EventType.TICK, symbol="INFY", price=102.0, ts=base + 301))
    assert any(e.type == EventType.BAR_CLOSE_5M for e in emitted)


@pytest.mark.asyncio
async def test_flush_all_emits_open_bars():
    emitted = []

    async def pub(ev: MarketEvent):
        emitted.append(ev)

    agg = BarAggregator(pub)
    ts = 1_700_000_100
    await agg.on_tick(MarketEvent(type=EventType.TICK, symbol="INFY", price=100.0, ts=ts))
    await agg.flush_all()
    assert any(e.type == EventType.BAR_CLOSE_5M for e in emitted)

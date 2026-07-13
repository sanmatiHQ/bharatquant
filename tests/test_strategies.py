"""Strategy unit tests — no live market data."""
from __future__ import annotations

import asyncio

import pytest

from src.events.types import EventType, MarketEvent
from src.strategies.base import MarketContext
from src.strategies.affordable_momentum import AffordableMomentumStrategy
from src.strategies.combined_momentum import CombinedMomentumStrategy
from src.strategies.gift_gap import GiftGapStrategy
from src.strategies.registry import StrategyRegistry, strategy_count
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
    assert len(reg._strategies) == strategy_count()
    assert strategy_count() == 31


@pytest.mark.asyncio
async def test_affordable_momentum_buy():
    import os

    os.environ["MAX_RUPEES_PER_TRADE"] = "2000"
    s = AffordableMomentumStrategy()
    ctx = MarketContext()
    await s.on_event(MarketEvent(type=EventType.SESSION_PRE_OPEN, symbol="ITC", price=280), ctx)
    sig = await s.on_event(MarketEvent(type=EventType.TICK, symbol="ITC", price=281.0), ctx)
    assert sig and sig.action == "BUY" and sig.strategy_id == "affordable_momentum"


def test_router_prefers_affordable_buy():
    import os

    from src.agent.router import AgentRouter
    from src.strategies.base import Signal

    os.environ["MAX_RUPEES_PER_TRADE"] = "2000"
    router = AgentRouter()
    router.ctx.last_ltp = {"ITC": 280, "TITAN": 4600}
    expensive = Signal("opening_range", "TITAN", "BUY", "MIS", 0.9, "orb")
    cheap = Signal("affordable_momentum", "ITC", "BUY", "MIS", 0.7, "mom")
    chosen = router.fuse([expensive, cheap], event_price=280, event_symbol="ITC")
    assert chosen and chosen.symbol == "ITC"


@pytest.mark.asyncio
async def test_macro_confluence_bull():
    from src.strategies.advanced_quant import MacroConfluenceStrategy

    s = MacroConfluenceStrategy()
    ctx = MarketContext(
        gift_nifty_change_pct=0.3,
        fii_net_cr=600,
        us_sp_change_pct=0.5,
        india_vix=13,
    )
    sig = await s.on_event(
        MarketEvent(type=EventType.GIFT_SESSION_CHANGE, payload={"us_sp": 0.5}),
        ctx,
    )
    assert sig and sig.action == "BUY"


@pytest.mark.asyncio
async def test_volume_breakout():
    from src.strategies.advanced_quant import VolumeBreakoutStrategy

    s = VolumeBreakoutStrategy()
    ctx = MarketContext()
    sig = await s.on_event(
        MarketEvent(
            type=EventType.BAR_CLOSE_5M,
            symbol="SBIN",
            price=800,
            payload={"high": 800, "close": 799, "vol_ratio": 2.5, "r3m": 0.01},
        ),
        ctx,
    )
    assert sig and sig.strategy_id == "volume_breakout"


@pytest.mark.asyncio
async def test_custom_rule_strategy():
    from src.strategies.custom_rules import CustomRuleSpec, CustomRuleStrategy
    from src.events.types import EventType

    spec = CustomRuleSpec(
        id="custom_test",
        listens={EventType.BAR_CLOSE_5M},
        conditions={"r3m_lt": 0, "rsi_lt": 40},
        action="BUY",
        rail="MIS",
        confidence=0.65,
        reason="test",
    )
    s = CustomRuleStrategy(spec)
    ctx = MarketContext()
    sig = await s.on_event(
        MarketEvent(
            type=EventType.BAR_CLOSE_5M,
            symbol="TCS",
            price=4000,
            payload={"r3m": -0.02, "rsi": 30},
        ),
        ctx,
    )
    assert sig and sig.strategy_id == "custom_test"
    from src.strategies.advanced_quant import AdaptiveAlphaStrategy

    s = AdaptiveAlphaStrategy()
    ctx = MarketContext(fii_net_cr=400, gift_nifty_change_pct=0.2, india_vix=14)
    sig = await s.on_event(
        MarketEvent(
            type=EventType.BAR_CLOSE_5M,
            symbol="INFY",
            price=1500,
            payload={"r3m": 0.02, "vol_ratio": 2.0, "rsi": 48},
        ),
        ctx,
    )
    assert sig and sig.action == "BUY"

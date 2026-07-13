"""Tests for market awareness + sentiment."""
from __future__ import annotations

import pytest

from src.strategies.base import MarketContext
from src.intelligence.sentiment_index import compute_fear_greed, sentiment_label
from src.strategies.market_session import market_clock_snapshot, is_nse_open, session_phase


def test_sentiment_label_bands():
    assert sentiment_label(80) == "Extreme Greed"
    assert sentiment_label(10) == "Extreme Fear"
    assert sentiment_label(50) == "Neutral"


def test_fear_greed_high_vix_is_fear():
    ctx = MarketContext(india_vix=28, fii_net_cr=-500, gift_nifty_change_pct=-0.3, llm_bias=-0.4)
    fg, label = compute_fear_greed(ctx)
    assert fg < 45
    assert "Fear" in label


def test_fear_greed_bullish_inputs():
    ctx = MarketContext(india_vix=13, fii_net_cr=800, gift_nifty_change_pct=0.4, llm_bias=0.5)
    fg, label = compute_fear_greed(ctx)
    assert fg > 55


def test_market_clock_snapshot_keys():
    snap = market_clock_snapshot(nse_status="Open")
    assert "session_phase" in snap
    assert "market_open" in snap
    assert "ist_date" in snap
    assert snap["nse_status"] == "Open"


@pytest.mark.asyncio
async def test_sentiment_regime_extreme_fear():
    from src.events.types import EventType, MarketEvent
    from src.strategies.sentiment_regime import SentimentRegimeStrategy

    s = SentimentRegimeStrategy()
    ctx = MarketContext(fear_greed_index=18, sentiment_label="Extreme Fear", market_open=True)
    sig = await s.on_event(MarketEvent(type=EventType.SESSION_OPEN, symbol="NIFTYBEES", price=250), ctx)
    assert sig and sig.action == "BUY"

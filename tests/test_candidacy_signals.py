"""New candidacy-only strategies: 52w-high proximity, low-vol anomaly, delivery conviction.

Each is proven against real bar_log/delivery data patterns before being trusted —
no strategy in this file has capital access; lifecycle default_state() keeps them
in 'candidacy' until they earn promotion the same as everything else.
"""
from __future__ import annotations

import os
import time

import pytest

from src.db.database import DB, DBConfig
from src.events.types import EventType, MarketEvent
from src.strategies.base import MarketContext
from src.strategies.candidacy_signals import (
    DeliveryConvictionStrategy,
    LowVolatilityAnomalyStrategy,
    Proximity52WHighStrategy,
)


@pytest.fixture
def db(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "t.db")
    return DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))


def _insert_daily_bars(db, symbol, closes, start_ts):
    day = 86400
    with db.tx() as conn:
        for i, c in enumerate(closes):
            ts = start_ts + i * day
            conn.execute(
                "INSERT INTO bar_log(ts,symbol,interval,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)",
                (ts, symbol, "1d", c, c * 1.01, c * 0.99, c, 100000),
            )


# ---------- Proximity52WHighStrategy ----------


@pytest.mark.asyncio
async def test_52w_high_fires_when_near_high(db):
    start = int(time.time()) - 260 * 86400
    closes = [100.0 + i * 0.15 for i in range(120)]  # steady uptrend, last close is the high
    _insert_daily_bars(db, "TCS", closes, start)
    strat = Proximity52WHighStrategy(db=db)
    event = MarketEvent(type=EventType.BAR_CLOSE_1D, symbol="NSE:TCS", price=closes[-1])
    sig = await strat.on_event(event, MarketContext())
    assert sig is not None
    assert sig.action == "BUY"
    assert sig.strategy_id == "proximity_52w_high"


@pytest.mark.asyncio
async def test_52w_high_silent_when_far_from_high(db):
    start = int(time.time()) - 260 * 86400
    closes = [100.0 + i * 0.15 for i in range(110)] + [90.0] * 10  # dropped well off the high
    _insert_daily_bars(db, "TCS", closes, start)
    strat = Proximity52WHighStrategy(db=db)
    event = MarketEvent(type=EventType.BAR_CLOSE_1D, symbol="NSE:TCS", price=closes[-1])
    sig = await strat.on_event(event, MarketContext())
    assert sig is None


@pytest.mark.asyncio
async def test_52w_high_silent_without_db():
    strat = Proximity52WHighStrategy(db=None)
    event = MarketEvent(type=EventType.BAR_CLOSE_1D, symbol="NSE:TCS", price=100.0)
    sig = await strat.on_event(event, MarketContext())
    assert sig is None


# ---------- LowVolatilityAnomalyStrategy ----------


@pytest.mark.asyncio
async def test_low_vol_fires_on_calm_uptrend(db):
    start = int(time.time()) - 25 * 86400
    closes = [100.0 + i * 0.05 for i in range(21)]  # very low daily vol, mild uptrend
    _insert_daily_bars(db, "HDFCBANK", closes, start)
    strat = LowVolatilityAnomalyStrategy(db=db)
    event = MarketEvent(type=EventType.BAR_CLOSE_1D, symbol="NSE:HDFCBANK", price=closes[-1])
    sig = await strat.on_event(event, MarketContext())
    assert sig is not None
    assert sig.action == "BUY"


@pytest.mark.asyncio
async def test_low_vol_silent_on_high_vol_series(db):
    start = int(time.time()) - 25 * 86400
    closes = []
    v = 100.0
    for i in range(21):
        v *= 1.05 if i % 2 == 0 else 0.94  # sawtooth — high realized vol
        closes.append(v)
    _insert_daily_bars(db, "ADANIENT", closes, start)
    strat = LowVolatilityAnomalyStrategy(db=db)
    event = MarketEvent(type=EventType.BAR_CLOSE_1D, symbol="NSE:ADANIENT", price=closes[-1])
    sig = await strat.on_event(event, MarketContext())
    assert sig is None


@pytest.mark.asyncio
async def test_low_vol_silent_on_negative_momentum(db):
    start = int(time.time()) - 25 * 86400
    closes = [100.0 - i * 0.05 for i in range(21)]  # calm but declining — should not fire
    _insert_daily_bars(db, "ITC", closes, start)
    strat = LowVolatilityAnomalyStrategy(db=db)
    event = MarketEvent(type=EventType.BAR_CLOSE_1D, symbol="NSE:ITC", price=closes[-1])
    sig = await strat.on_event(event, MarketContext())
    assert sig is None


# ---------- DeliveryConvictionStrategy ----------


@pytest.mark.asyncio
async def test_delivery_conviction_fires_on_high_delivery_up_day(db):
    start = int(time.time()) - 3 * 86400
    _insert_daily_bars(db, "RELIANCE", [2900.0, 2950.0], start)
    strat = DeliveryConvictionStrategy(db=db)
    event = MarketEvent(
        type=EventType.VOLUME_ANOMALY,
        symbol="NSE:RELIANCE",
        payload={"symbol": "RELIANCE", "delivery_pct": 78.0},
    )
    sig = await strat.on_event(event, MarketContext())
    assert sig is not None
    assert sig.action == "BUY"
    assert sig.strategy_id == "delivery_conviction"


@pytest.mark.asyncio
async def test_delivery_conviction_silent_on_low_delivery(db):
    start = int(time.time()) - 3 * 86400
    _insert_daily_bars(db, "RELIANCE", [2900.0, 2950.0], start)
    strat = DeliveryConvictionStrategy(db=db)
    event = MarketEvent(
        type=EventType.VOLUME_ANOMALY,
        symbol="NSE:RELIANCE",
        payload={"symbol": "RELIANCE", "delivery_pct": 40.0},
    )
    sig = await strat.on_event(event, MarketContext())
    assert sig is None


@pytest.mark.asyncio
async def test_delivery_conviction_silent_on_down_day_even_with_high_delivery(db):
    start = int(time.time()) - 3 * 86400
    _insert_daily_bars(db, "RELIANCE", [2950.0, 2900.0], start)
    strat = DeliveryConvictionStrategy(db=db)
    event = MarketEvent(
        type=EventType.VOLUME_ANOMALY,
        symbol="NSE:RELIANCE",
        payload={"symbol": "RELIANCE", "delivery_pct": 90.0},
    )
    sig = await strat.on_event(event, MarketContext())
    assert sig is None


# ---------- lifecycle: new strategies must default to candidacy, not full ----------


def test_new_strategies_default_to_candidacy(db):
    from src.agent.strategy_lifecycle import ensure_lifecycle_row

    for sid in ("proximity_52w_high", "low_vol_anomaly", "delivery_conviction"):
        state = ensure_lifecycle_row(db, sid)
        assert state == "candidacy", f"{sid} must start in candidacy, got {state}"

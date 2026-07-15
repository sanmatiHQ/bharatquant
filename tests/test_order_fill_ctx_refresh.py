"""Stale-context audit finding: ctx.positions was set once at engine startup and
never refreshed after a live fill settled through order_fill_handler.py. Same
bug class independently reported elsewhere: agent sat idle for hours thinking
it was maxed out because it never saw positions had actually closed.
"""
from __future__ import annotations

import os

import pytest

from src.db.database import DB, DBConfig
from src.events.types import EventType, MarketEvent
from src.exec.order_fill_handler import on_order_fill
from src.exec.pending_orders import record_pending
from src.strategies.base import MarketContext


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DAILY_INVESTMENT_MAX", "50000")  # this test is about ctx refresh, not budget gating
    return DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))


@pytest.mark.asyncio
async def test_ctx_positions_refreshed_after_live_buy_fill(db):
    record_pending(
        db, order_id="LIVE-1", symbol="TCS", side="BUY", qty=5, price=3800.0,
        rail="CNC", strategy_id="fii_regime", reason="test",
    )
    ctx = MarketContext()
    ctx.positions = {}  # simulates the stale startup snapshot with no TCS yet

    event = MarketEvent(
        type=EventType.ORDER_FILL, symbol="NSE:TCS", price=3800.0,
        payload={"order_id": "LIVE-1", "symbol": "TCS", "fill_price": 3800.0, "qty": 5, "status": "COMPLETE"},
    )
    await on_order_fill(db, event, ctx=ctx)

    assert "TCS" in ctx.positions, "ctx.positions must reflect the fill that just settled, not the stale startup snapshot"
    assert ctx.positions["TCS"]["qty"] == 5


@pytest.mark.asyncio
async def test_on_order_fill_without_ctx_does_not_crash(db):
    """Backward compatible — ctx is optional, callers that don't pass it still work."""
    record_pending(
        db, order_id="LIVE-2", symbol="INFY", side="BUY", qty=2, price=1500.0,
        rail="CNC", strategy_id="fii_regime", reason="test",
    )
    event = MarketEvent(
        type=EventType.ORDER_FILL, symbol="NSE:INFY", price=1500.0,
        payload={"order_id": "LIVE-2", "symbol": "INFY", "fill_price": 1500.0, "qty": 2, "status": "COMPLETE"},
    )
    await on_order_fill(db, event)  # no ctx passed — must not raise

    row = db._conn.execute("SELECT qty FROM positions WHERE symbol='INFY'").fetchone()
    assert row is not None and row["qty"] == 2


@pytest.mark.asyncio
async def test_ctx_positions_refreshed_on_reconciliation_path(db):
    """The 'already have a trades row, just reconcile price' branch must also
    refresh ctx.positions, not just the settle_pending_fill success branch."""
    ts = 1_700_000_000
    db.record_trade(ts, "WIPRO", "BUY", 3, 400.0, 1200.0, "test", 0.0, "NA", order_id="LIVE-3")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO positions(symbol, qty, avg_price, last_price, open_ts) VALUES (?,?,?,?,?)",
            ("WIPRO", 3, 400.0, 400.0, ts),
        )
    ctx = MarketContext()
    ctx.positions = {}

    event = MarketEvent(
        type=EventType.ORDER_FILL, symbol="NSE:WIPRO", price=405.0,
        payload={"order_id": "LIVE-3", "symbol": "WIPRO", "fill_price": 405.0, "qty": 3, "status": "COMPLETE"},
    )
    await on_order_fill(db, event, ctx=ctx)

    assert "WIPRO" in ctx.positions
    assert ctx.positions["WIPRO"]["last_price"] == pytest.approx(405.0)

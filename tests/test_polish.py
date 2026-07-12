from __future__ import annotations

import asyncio
import time

import pytest

from src.db.database import DB, DBConfig
from src.events import EventBus, EventType, MarketEvent
from src.data.tick_recorder import TickRecorder
from src.exec.order_fill_handler import on_order_fill, paper_fill_event
from src.ops.daily_tax_summary import build_daily_summary, persist_daily_summary
from src.data.sector_mapper import load_sector_map, sector_for_symbol
from src.strategies.earnings_vol import EarningsVolStrategy
from src.strategies.global_risk_beta import GlobalRiskBetaStrategy
from src.strategies.base import MarketContext


@pytest.mark.asyncio
async def test_eventbus_publish_subscribe():
    bus = EventBus()
    seen = []

    async def handler(ev: MarketEvent) -> None:
        seen.append(ev.symbol)

    bus.subscribe(EventType.TICK, handler)
    bus.publish_nowait(MarketEvent(type=EventType.TICK, symbol="INFY", price=100))
    task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.05)
    bus.stop()
    task.cancel()
    assert seen == ["INFY"]


@pytest.mark.asyncio
async def test_recorder_15m_bar(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "r.db")))
    rec = TickRecorder(db)
    await rec.on_event(
        MarketEvent(
            type=EventType.BAR_CLOSE_15M,
            symbol="TCS",
            price=400,
            payload={"open": 398, "high": 401, "low": 397, "close": 400, "volume": 1000},
        )
    )
    rec.flush()
    row = db._conn.execute("SELECT interval FROM bar_log WHERE symbol='TCS'").fetchone()
    assert row["interval"] == "15m"


def test_order_id_on_trade(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))
    db.record_trade(1, "INFY", "BUY", 1, 100, 100, "t", 0, "NA", order_id="OID-1")
    row = db._conn.execute("SELECT order_id FROM trades").fetchone()
    assert row["order_id"] == "OID-1"


@pytest.mark.asyncio
async def test_order_fill_reconcile(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "f.db")))
    db.record_trade(1, "INFY", "BUY", 10, 100, 1000, "t", 0, "NA", order_id="OID-2")
    ev = paper_fill_event("INFY", "BUY", 10, 101.5, "OID-2")
    await on_order_fill(db, ev)
    row = db._conn.execute("SELECT price FROM trades WHERE order_id='OID-2'").fetchone()
    assert float(row["price"]) == 101.5


def test_daily_tax_summary(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "tax.db")))
    db.record_trade(int(time.time()), "INFY", "SELL", 5, 110, 550, "x", 5, "STCG", order_id="S1")
    s = build_daily_summary(db)
    assert "net_after_tax_inr" in s
    persist_daily_summary(db)
    row = db._conn.execute("SELECT net_after_tax FROM daily_tax_summary").fetchone()
    assert row is not None


def test_sector_mapper(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "sec.db")))
    csv = tmp_path / "sectors.csv"
    csv.write_text("symbol,sector\nINFY,IT\n", encoding="utf-8")
    assert load_sector_map(db, csv) == 1
    assert sector_for_symbol("INFY", db) == "IT"


@pytest.mark.asyncio
async def test_earnings_vol_strategy():
    s = EarningsVolStrategy()
    ctx = MarketContext(india_vix=20)
    sig = await s.on_event(
        MarketEvent(type=EventType.NEWS_ALERT, symbol="INFY", payload={"desc": "Q4 earnings results"}),
        ctx,
    )
    assert sig and sig.action == "HEDGE"


@pytest.mark.asyncio
async def test_global_risk_beta():
    s = GlobalRiskBetaStrategy()
    ctx = MarketContext()
    sig = await s.on_event(
        MarketEvent(type=EventType.GIFT_SESSION_CHANGE, payload={"us_sp": -1.2, "crude": 3.0}),
        ctx,
    )
    assert sig and ctx.regime == "RISK_OFF"

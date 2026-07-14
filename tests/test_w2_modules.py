from __future__ import annotations

import time

from src.accounting.fifo_lots import close_lots_fifo, open_lot
from src.costs.cost_engine import CostEngine
from src.db.database import DB, DBConfig
from src.agent.regime_classifier import classify_regime, regime_strategy_whitelist
from src.risk.event_calendar import seed_calendar_year, today_risk_level, mis_allowed_today
from src.agent.kelly_sizing import kelly_fraction
from src.agent.var_breaker import historical_var


def test_fifo_roundtrip(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "f.db")))
    db.add_cash(1, 50_000.0, "seed")
    ts = int(time.time())
    open_lot(db, "INFY", 10, 100.0, ts, "CNC", 1)
    fills, tax = close_lots_fifo(db, "INFY", 10, 110.0, ts + 86400 * 10, CostEngine(0))
    assert len(fills) == 1
    assert tax == "STCG"
    assert fills[0].pnl == 100.0


def test_regime_classifier():
    from src.agent.regime_classifier import classify_regime_from_prices
    import numpy as np

    r = classify_regime([0.002] * 20, vix=15)
    assert r.label in ("BULL", "BEAR", "SIDEWAYS", "HIGH_VOL")
    bull = classify_regime_from_prices(np.linspace(100, 120, 60), vix=14)
    assert bull.label == "BULL"
    panic = classify_regime_from_prices(np.linspace(100, 105, 30), vix=25)
    assert panic.label == "HIGH_VOL"
    wl = regime_strategy_whitelist("BULL")
    assert "combined_momentum" in wl
    neutral_wl = regime_strategy_whitelist("NEUTRAL")
    assert "opening_range" in neutral_wl
    assert "combined_momentum" in neutral_wl


def test_corporate_activity_normalization_and_snapshot(tmp_path):
    import json

    from src.data.provenance import record_ingest
    from src.events.types import EventType
    from src.intelligence.corporate_activity import (
        classify_corp_category,
        load_corporate_activity,
        normalize_bulk,
        normalize_insider,
    )

    assert classify_corp_category("Board declares interim dividend of Rs 5") == "dividend"
    assert classify_corp_category("Promoter group acquisition of shares") == "promoter"

    ins = normalize_insider({"symbol": "INFY", "personName": "Promoter X", "acqMode": "Buy", "secAcq": 1000})
    assert ins["category"] == "promoter"
    assert ins["side"] == "buy"

    bulk = normalize_bulk({"symbol": "TCS", "clientName": "ABC Fund", "buySell": "BUY", "qty": 250000, "price": 3500})
    assert bulk["side"] == "buy"
    assert "ABC Fund" in bulk["reason"]

    db = DB(DBConfig(sqlite_path=str(tmp_path / "corp.db")))
    with db.tx() as conn:
        record_ingest(
            conn,
            source="test",
            event_type=EventType.INSIDER_FILING,
            payload={"symbol": "INFY", "personName": "Director Y", "acqMode": "Buy"},
            execution_allowed=False,
        )
        record_ingest(
            conn,
            source="test",
            event_type=EventType.BLOCK_DEAL,
            payload={"symbol": "TCS", "clientName": "FII", "buySell": "BUY", "qty": 500000},
            execution_allowed=False,
        )
        record_ingest(
            conn,
            source="test",
            event_type=EventType.NEWS_ALERT,
            payload={"symbol": "HDFC", "desc": "Declaration of dividend Rs 10 per share"},
            execution_allowed=False,
        )
        record_ingest(
            conn,
            source="test",
            event_type=EventType.FII_DII_UPDATE,
            payload={"fii_net": 1200, "dii_net": -300, "date": "2026-07-12"},
            execution_allowed=False,
        )
    snap = load_corporate_activity(db, lookback_days=7)
    assert snap["counts"]["insider"] >= 1
    assert snap["counts"]["bulk"] >= 1
    assert snap["counts"]["dividends"] >= 1
    assert snap["counts"]["mass_flow"] >= 1
    assert len(snap["timeline"]) >= 3


def test_corporate_profit_tilt(tmp_path):
    from src.intelligence.corporate_activity import corporate_profit_tilt
    from src.strategies.base import MarketContext
    import json

    db = DB(DBConfig(sqlite_path=str(tmp_path / "corp.db")))
    payload = {
        "patterns": {"BLOCK_DEAL:block_deal:buy:other": 1.12, "INSIDER_FILING:insider:sell:other": 0.78},
        "strategies": {},
    }
    db._conn.execute(
        "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        ("institutional_learn_weights", json.dumps(payload)),
    )
    db._conn.commit()
    ctx = MarketContext(
        recent_corporate=[
            {"symbol": "TCS", "kind": "bulk", "side": "buy", "category": "block_deal", "entity_class": "other"},
            {"symbol": "RELIANCE", "kind": "insider", "side": "sell", "category": "insider", "entity_class": "other"},
        ],
    )
    ctx.institutional_weights = payload
    mult, reasons = corporate_profit_tilt("TCS", ctx)
    assert mult > 1.0
    assert any("learned" in r for r in reasons)

    mult2, reasons2 = corporate_profit_tilt("RELIANCE", ctx)
    assert mult2 < 1.0

    mult3, _ = corporate_profit_tilt("INFY", ctx)
    assert mult3 == 1.0


def test_tick_ring_buffer():
    from src.feeds.bar_aggregator import TickRingBuffer

    ring = TickRingBuffer(capacity=8)
    for px in [100, 101, 102, 103]:
        ring.push("INFY", px)
    w = ring.window("INFY")
    assert len(w) == 4
    assert float(w[-1]) == 103.0
    assert ring.atr_bps("INFY") > 0


def test_session_ledger(tmp_path):
    from src.ops.session_ledger import build_session_ledger

    db = DB(DBConfig(sqlite_path=str(tmp_path / "s.db")))
    db.add_cash(1, 10_000.0, "seed")
    ts = int(time.time())
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO trades(ts,symbol,side,qty,price,amount,reason) VALUES (?,?,?,?,?,?,?)",
            (ts, "INFY", "BUY", 1, 100.0, 100.0, "test_buy"),
        )
        conn.execute(
            "INSERT INTO trades(ts,symbol,side,qty,price,amount,reason) VALUES (?,?,?,?,?,?,?)",
            (ts + 60, "INFY", "SELL", 1, 98.0, 98.0, "test_sell"),
        )
    led = build_session_ledger(db)
    assert led["trade_count"] >= 2
    assert led["pnl"]["realized"] == -2.0
    assert "plan" in led["plan_for_tomorrow"].lower() or "08:45" in led["plan_for_tomorrow"]


def test_event_calendar(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "c.db")))
    n = seed_calendar_year(db, 2026)
    assert n >= 5
    assert today_risk_level(db) in ("low", "medium", "high")
    assert isinstance(mis_allowed_today(db), bool)


def test_kelly_and_var():
    k = kelly_fraction(0.6, 1.5, 1.0)
    assert 0 <= k <= 1
    v = historical_var([0.01, -0.02, 0.005, -0.03, 0.01] * 5)
    assert v >= 0


def test_institutional_entity_classifier():
    from src.intelligence.institutional_entities import classify_entity, entity_confidence_boost

    assert classify_entity("HDFC Mutual Fund") == "mf"
    assert classify_entity("Goldman Sachs Singapore") == "fii"
    assert classify_entity("ICICI Bank Ltd") == "bank"
    assert classify_entity("Promoter Group") == "promoter"
    assert entity_confidence_boost("mf", "buy") > 0


def test_event_outcomes_and_learning(tmp_path):
    import json
    import time

    from src.data.provenance import record_ingest
    from src.events.types import EventType
    from src.intelligence.event_outcomes import label_pending_events
    from src.intelligence.institutional_learning import learn_institutional_weights, seed_rl_transitions_from_outcomes

    db = DB(DBConfig(sqlite_path=str(tmp_path / "learn.db")))
    base_ts = int(time.time()) - 10 * 86400
    with db.tx() as conn:
        record_ingest(
            conn,
            source="test",
            event_type=EventType.BLOCK_DEAL,
            payload={"symbol": "INFY", "clientName": "HDFC Mutual Fund", "buySell": "BUY", "qty": 300000, "price": 100.0},
            execution_allowed=False,
        )
        conn.execute(
            "UPDATE ingest_log SET ts=? WHERE id=(SELECT MAX(id) FROM ingest_log)",
            (base_ts,),
        )
        for i, px in enumerate([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]):
            conn.execute(
                "INSERT INTO tick_log(ts,symbol,ltp,volume) VALUES (?,?,?,?)",
                (base_ts + i * 86400, "INFY", px, 1000),
            )
    meta = label_pending_events(db, now=base_ts + 8 * 86400)
    assert meta["labeled"] >= 1
    row = db._conn.execute("SELECT ret_5d FROM corporate_event_outcomes WHERE symbol='INFY'").fetchone()
    assert row and float(row["ret_5d"]) > 0
    # Seed enough samples for learning
    with db.tx() as conn:
        for i in range(3):
            conn.execute(
                """
                INSERT INTO corporate_event_outcomes(
                  event_ts, symbol, event_type, category, side, entity_class,
                  entry_price, ret_5d, ret_20d, labeled_ts
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (base_ts + i, "TCS", "BLOCK_DEAL", "block_deal", "buy", "mf", 100.0, 2.5, 4.0, int(time.time())),
            )
    weights = learn_institutional_weights(db)
    assert "bulk_accumulation" in weights or isinstance(weights, dict)
    rl = seed_rl_transitions_from_outcomes(db)
    assert rl["pushed"] >= 1
    n = db._conn.execute("SELECT COUNT(*) c FROM rl_transitions").fetchone()["c"]
    assert n >= 1


def test_shareholding_normalize():
    from src.intelligence.corporate_activity import normalize_shareholding

    sh = normalize_shareholding(
        {"symbol": "RELIANCE", "mf_pct": 8.2, "public_pct": 50.0, "deltas": {"public_pct": 0.6, "promoter_pct": -0.1}}
    )
    assert sh["kind"] == "shareholding"
    assert sh["side"] == "buy"
    assert "promoter" in sh["reason"]


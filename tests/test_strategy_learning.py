"""Unified strategy learning tests."""
from __future__ import annotations

import json
import time

import pytest

from src.db.database import DB, DBConfig
from src.intelligence.strategy_learning import (
    KEY_LEARNED_CUSTOM,
    KEY_STRATEGY_WEIGHTS,
    label_strategy_signals,
    learn_unified_strategy_weights,
    promote_discovery_rules,
    refresh_all_learning,
)
from src.strategies.base import MarketContext


@pytest.fixture
def db(tmp_path):
    d = DB(DBConfig(sqlite_path=str(tmp_path / "learn.db")))
    return d


def _seed_ledger_and_bars(db: DB) -> int:
    ts = int(time.time()) - 7200
    db._conn.execute(
        """
        INSERT INTO strategy_ledger(ts, strategy_id, symbol, event_type, signal, confidence, price, executed, reason)
        VALUES (?, 'connors_ibs', 'INFY', 'BAR_CLOSE_5M', 'BUY', 0.7, 1500, 0, 'ibs_test')
        """,
        (ts,),
    )
    for i, close in enumerate([1490, 1495, 1500, 1505, 1510, 1515]):
        db._conn.execute(
            """
            INSERT INTO bar_log(ts, symbol, interval, open, high, low, close, volume)
            VALUES (?, 'INFY', '5m', ?, ?, ?, ?, 1000)
            """,
            (ts + i * 300, close, close + 2, close - 2, close),
        )
    db._conn.commit()
    return ts


def test_label_strategy_signals(db):
    _seed_ledger_and_bars(db)
    meta = label_strategy_signals(db)
    assert meta["labeled"] >= 1
    row = db._conn.execute(
        "SELECT ret_15m FROM strategy_signal_outcomes WHERE strategy_id='connors_ibs'"
    ).fetchone()
    assert row and row["ret_15m"] is not None


def test_learn_unified_weights_from_outcomes(db):
    _seed_ledger_and_bars(db)
    label_strategy_signals(db)
    for _ in range(6):
        ts = int(time.time()) - 8000 - _ * 10
        db._conn.execute(
            """
            INSERT INTO strategy_signal_outcomes(
              ledger_ts, strategy_id, symbol, signal, confidence, executed, entry_price, ret_15m, labeled_ts
            ) VALUES (?, 'momentum_consensus', 'TCS', 'BUY', 0.8, 0, 4000, 0.5, ?)
            """,
            (ts, int(time.time())),
        )
    db._conn.commit()
    weights = learn_unified_strategy_weights(db)
    assert "momentum_consensus" in weights
    stored = json.loads(
        db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_STRATEGY_WEIGHTS,)).fetchone()["v"]
    )
    assert stored["strategies"]["momentum_consensus"] >= 1.0


def test_promote_discovery_rules(db):
    db._conn.execute(
        """
        INSERT INTO strategy_discovery(rule_id, symbol, conditions, win_rate, avg_return, sample_count, discovered_ts, promoted)
        VALUES ('ibs_oversold_INFY', 'INFY', ?, 0.58, 0.4, 25, ?, 0)
        """,
        (
            json.dumps({"rule_id": "ibs_oversold", "field": "ibs", "op": "lt", "threshold": 0.2, "source": "quantifiedstrategies"}),
            int(time.time()),
        ),
    )
    db._conn.commit()
    promoted = promote_discovery_rules(db)
    assert len(promoted) == 1
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_LEARNED_CUSTOM,)).fetchone()
    assert row
    specs = json.loads(row["v"])
    assert specs[0]["id"].startswith("learned_")


def test_refresh_all_learning(db):
    _seed_ledger_and_bars(db)
    ctx = MarketContext()
    meta = refresh_all_learning(db, ctx)
    assert "strategy_weights" in meta
    assert ctx.strategy_learn_weights is not None

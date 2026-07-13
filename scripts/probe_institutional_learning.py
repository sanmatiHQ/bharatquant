#!/usr/bin/env python3.11
"""
E2E proof: institutional ingest → outcome labels → learned weights → RL transitions.

Usage (local):
  python3.11 scripts/probe_institutional_learning.py

Usage (VM):
  sudo -u bharatquant bash -lc 'cd /opt/bharatquant/zerodha-momo-rl && set -a && source /etc/bharatquant/env && set +a && python3.11 scripts/probe_institutional_learning.py --db'

Optional live NSE shareholding fetch (one symbol):
  python3.11 scripts/probe_institutional_learning.py --live RELIANCE
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.bandit import StrategyBandit
from src.data.provenance import record_ingest
from src.db.database import DB, DBConfig
from src.events.types import EventType
from src.intelligence.event_outcomes import label_pending_events
from src.intelligence.institutional_entities import classify_entity
from src.intelligence.institutional_learning import (
    KEY_WEIGHTS,
    load_institutional_weights,
    refresh_context_learning,
    seed_rl_transitions_from_outcomes,
)
from src.strategies.base import MarketContext
from src.strategies.registry import StrategyRegistry, strategy_count


def _ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")
    raise SystemExit(1)


def _synthetic_proof(db: DB) -> dict:
    base_ts = int(time.time()) - 12 * 86400
    with db.tx() as conn:
        record_ingest(
            conn,
            source="probe",
            event_type=EventType.BLOCK_DEAL,
            payload={
                "symbol": "INFY",
                "clientName": "HDFC Mutual Fund",
                "entity_class": "mf",
                "buySell": "BUY",
                "qty": 400000,
                "price": 1500.0,
            },
            execution_allowed=False,
        )
        conn.execute(
            "UPDATE ingest_log SET ts=? WHERE id=(SELECT MAX(id) FROM ingest_log)",
            (base_ts,),
        )
        for i, px in enumerate([1500.0, 1510.0, 1520.0, 1530.0, 1540.0, 1550.0, 1560.0, 1570.0]):
            conn.execute(
                "INSERT INTO tick_log(ts,symbol,ltp,volume) VALUES (?,?,?,?)",
                (base_ts + i * 86400, "INFY", px, 5000),
            )
        for i in range(4):
            conn.execute(
                """
                INSERT INTO corporate_event_outcomes(
                  event_ts, symbol, event_type, category, side, entity_class,
                  entry_price, ret_5d, ret_20d, labeled_ts
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    base_ts + i,
                    "TCS",
                    "BLOCK_DEAL",
                    "block_deal",
                    "buy",
                    "mf",
                    100.0,
                    3.2,
                    5.0,
                    int(time.time()),
                ),
            )

    label = label_pending_events(db, now=base_ts + 8 * 86400)
    if label.get("labeled", 0) < 1:
        _fail(f"label_pending_events labeled={label}")

    row = db._conn.execute(
        "SELECT ret_5d FROM corporate_event_outcomes WHERE symbol='INFY'"
    ).fetchone()
    if not row or float(row["ret_5d"]) <= 0:
        _fail(f"INFY forward return not positive: {row}")

    ctx = MarketContext()
    meta = refresh_context_learning(db, ctx)
    if not ctx.institutional_weights.get("strategies"):
        _fail("institutional_weights.strategies empty after refresh")

    rl_n = db._conn.execute("SELECT COUNT(*) c FROM rl_transitions").fetchone()["c"]
    if rl_n < 1:
        _fail(f"rl_transitions count={rl_n}")

    bandit = StrategyBandit(db)
    reg = StrategyRegistry()
    reg_ids = {s.id for s in reg._strategies}
    for sid in ("bulk_accumulation", "bulk_distribution", "institutional_flow"):
        if sid not in reg_ids:
            _fail(f"registry missing strategy {sid}")
        with db.tx() as conn:
            conn.execute(
                """
                INSERT INTO strategy_ledger(ts, strategy_id, symbol, event_type, signal, confidence, executed, reason)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (int(time.time()), sid, "INFY", "BLOCK_DEAL", "BUY", 0.7, 1, "probe_seed"),
            )
    weights = bandit.update_weights()
    for sid in ("bulk_accumulation", "bulk_distribution", "institutional_flow"):
        if sid not in weights:
            _fail(f"bandit missing strategy {sid} after ledger seed")

    return {"label": label, "rl_transitions": rl_n, "meta": meta, "bandit_keys": list(weights.keys())}


def _db_proof(db: DB) -> dict:
    """Read-only proof against production SQLite."""
    out: dict = {}
    out["ingest_types"] = {
        r["event_type"]: r["c"]
        for r in db._conn.execute(
            """
            SELECT event_type, COUNT(*) c FROM ingest_log
            WHERE event_type IN ('BLOCK_DEAL','INSIDER_FILING','SHAREHOLDING_UPDATE','MF_HOLDING_UPDATE')
            GROUP BY event_type
            """
        ).fetchall()
    }
    out["outcomes_labeled"] = db._conn.execute(
        "SELECT COUNT(*) c FROM corporate_event_outcomes WHERE ret_5d IS NOT NULL"
    ).fetchone()["c"]
    out["shareholding_rows"] = db._conn.execute(
        "SELECT COUNT(*) c FROM shareholding_snapshots"
    ).fetchone()["c"]
    out["rl_transitions"] = db._conn.execute("SELECT COUNT(*) c FROM rl_transitions").fetchone()["c"]
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_WEIGHTS,)).fetchone()
    out["learn_weights"] = json.loads(row["v"]) if row else {}
    ctx = MarketContext()
    refresh_context_learning(db, ctx)
    out["refresh"] = {"strategies": list((ctx.institutional_weights or {}).get("strategies", {}).keys())}
    return out


async def _live_shareholding(symbol: str) -> dict | None:
    from src.ingest.nse_shareholding import fetch_shareholding

    return await fetch_shareholding(symbol)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="store_true", help="Prove against SQLITE_PATH (VM/prod)")
    ap.add_argument("--live", metavar="SYMBOL", help="Live NSE shareholding fetch for one symbol")
    args = ap.parse_args()

    print("== institutional learning E2E proof ==")
    _ok(f"strategy_count={strategy_count()} (expect 33)")
    _ok(f"classify_entity('HDFC Mutual Fund')={classify_entity('HDFC Mutual Fund')}")

    if args.live:
        print(f"== live NSE shareholding: {args.live} ==")
        snap = asyncio.run(_live_shareholding(args.live))
        if not snap:
            _fail("live shareholding fetch returned None")
        print(json.dumps(snap, indent=2))
        _ok(f"live shareholding {args.live} parsed")

    if args.db:
        path = os.environ.get("SQLITE_PATH", "/var/lib/bharatquant/trading.db")
        db = DB(DBConfig(sqlite_path=path))
        report = _db_proof(db)
        print(json.dumps(report, indent=2, default=str))
        _ok(f"DB proof on {path}")
        return

    with tempfile.TemporaryDirectory() as td:
        db = DB(DBConfig(sqlite_path=str(Path(td) / "probe.db")))
        report = _synthetic_proof(db)
        print(json.dumps({k: v for k, v in report.items() if k != "meta"}, indent=2, default=str))
        _ok("synthetic E2E chain: ingest → label → learn → RL → bandit")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()

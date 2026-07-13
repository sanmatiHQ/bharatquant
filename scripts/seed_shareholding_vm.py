#!/usr/bin/env python3.11
"""One-shot: fetch live shareholding + persist + refresh learning on VM."""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = "/opt/bharatquant/zerodha-momo-rl"
sys.path.insert(0, ROOT)

from src.data.provenance import record_ingest, tag_payload
from src.db.database import DB, DBConfig
from src.events.types import EventType
from src.ingest.nse_shareholding import _persist_snapshot, fetch_shareholding
from src.intelligence.institutional_learning import refresh_context_learning
from src.strategies.base import MarketContext


async def main() -> None:
    db = DB(DBConfig(sqlite_path=os.environ["SQLITE_PATH"]))
    snap = await fetch_shareholding("INFY")
    if not snap:
        print("FAIL no shareholding snap")
        raise SystemExit(1)
    payload = tag_payload(snap, source="probe_seed", execution_allowed=False)
    _persist_snapshot(db, snap, payload)
    with db.tx() as conn:
        record_ingest(
            conn,
            source="probe_seed",
            event_type=EventType.SHAREHOLDING_UPDATE,
            payload=payload,
            execution_allowed=False,
        )
    ctx = MarketContext()
    meta = refresh_context_learning(db, ctx)
    shp = db._conn.execute("SELECT COUNT(*) c FROM shareholding_snapshots").fetchone()["c"]
    ing = db._conn.execute(
        "SELECT COUNT(*) c FROM ingest_log WHERE event_type='SHAREHOLDING_UPDATE'"
    ).fetchone()["c"]
    print("PASS shareholding_seed", {"symbol": snap["symbol"], "shp_rows": shp, "ingest_shp": ing, "meta": meta})


if __name__ == "__main__":
    asyncio.run(main())

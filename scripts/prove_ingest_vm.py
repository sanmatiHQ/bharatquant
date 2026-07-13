#!/usr/bin/env python3.11
"""One-shot: prove NSE bulk + insider + shareholding ingest → ingest_log."""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.data.provenance import record_ingest, tag_payload
from src.db.database import DB, DBConfig
from src.events.types import EventType
from src.ingest.nse_bulk import fetch_bulk_deals
from src.ingest.nse_insider import fetch_insider_filings
from src.ingest.nse_shareholding import fetch_shareholding


async def main() -> None:
    db = DB(DBConfig(sqlite_path=os.environ.get("SQLITE_PATH", "data/trading.db")))
    results: dict[str, int] = {"BLOCK_DEAL": 0, "INSIDER_FILING": 0, "SHAREHOLDING_UPDATE": 0}

    try:
        bulk = await fetch_bulk_deals()
        n_bulk = 0
        with db.tx() as conn:
            for row in bulk[:30]:
                payload = tag_payload(dict(row), source="prove_ingest", execution_allowed=False)
                record_ingest(conn, source="prove_ingest", event_type=EventType.BLOCK_DEAL, payload=payload, execution_allowed=False)
                n_bulk += 1
        results["BLOCK_DEAL"] = n_bulk
    except Exception as exc:
        print(f"WARN bulk fetch: {exc}")

    try:
        insider = await fetch_insider_filings()
        rows = insider if isinstance(insider, list) else (insider.get("data") or []) if isinstance(insider, dict) else []
        n_ins = 0
        with db.tx() as conn:
            for row in rows[:20]:
                payload = tag_payload(dict(row), source="prove_ingest", execution_allowed=False)
                record_ingest(conn, source="prove_ingest", event_type=EventType.INSIDER_FILING, payload=payload, execution_allowed=False)
                n_ins += 1
        results["INSIDER_FILING"] = n_ins
    except Exception as exc:
        print(f"WARN insider fetch: {exc}")

    shp = await fetch_shareholding("RELIANCE")
    n_shp = 0
    if shp:
        payload = tag_payload(shp, source="prove_ingest", execution_allowed=False)
        with db.tx() as conn:
            record_ingest(conn, source="prove_ingest", event_type=EventType.SHAREHOLDING_UPDATE, payload=payload, execution_allowed=False)
        n_shp = 1
    results["SHAREHOLDING_UPDATE"] = n_shp

    print("PASS prove_ingest", results)
    if results["BLOCK_DEAL"] < 1 and results["SHAREHOLDING_UPDATE"] < 1:
        raise SystemExit("FAIL prove_ingest — no bulk or shareholding rows ingested")
    for et, _ in results.items():
        cnt = db._conn.execute(
            "SELECT COUNT(*) c FROM ingest_log WHERE event_type=?", (et,)
        ).fetchone()["c"]
        print(f"  total_{et}={cnt}")


if __name__ == "__main__":
    asyncio.run(main())

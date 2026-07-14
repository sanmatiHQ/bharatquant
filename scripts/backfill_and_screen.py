#!/usr/bin/env python3.11
"""Backfill bar_log from Kite historical() then screen all registry strategies."""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.backtest.historical_backfill import backfill_universe
from src.backtest.walk_forward import run_registry_historical_screen
from src.db.database import DB, DBConfig


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="data/universe_full_nse.csv")
    p.add_argument("--skip-backfill", action="store_true")
    p.add_argument("--years", type=float, default=2.0)
    p.add_argument("--max-symbols", type=int, default=int(os.getenv("HIST_BACKFILL_MAX_SYMBOLS", "80")))
    p.add_argument("--lookback-days", type=int, default=365)
    p.add_argument("--symbol-limit", type=int, default=40)
    args = p.parse_args()

    db_path = os.getenv("SQLITE_PATH", "data/trading.db")
    db = DB(DBConfig(sqlite_path=db_path))

    out: dict = {}
    if not args.skip_backfill:
        out["backfill"] = backfill_universe(
            db,
            args.universe,
            years=args.years,
            max_symbols=args.max_symbols,
        )
    results = run_registry_historical_screen(
        db,
        symbol_limit=args.symbol_limit,
        lookback_days=args.lookback_days,
    )
    out["screen_count"] = len(results)
    out["cleared"] = [r for r in results if r.get("cleared")]
    out["results"] = sorted(results, key=lambda x: float(x.get("composite") or 0), reverse=True)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3.11
"""Walk-forward backtest CLI — Kite historical or CSV panel.

Usage:
  python3.11 scripts/backtest.py --symbols INFY,TCS,RELIANCE,NIFTYBEES --days 400
  python3.11 scripts/backtest.py --universe-csv data/universe_full_nse.csv --top 30 --days 500
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.backtest.walk_forward import BacktestConfig, run_walk_forward
from src.data.instruments import InstrumentStore
from src.data.kite_data_feed import KiteDataFeed
from src.db.database import DB, DBConfig


def fetch_panel(symbols: list[str], days: int) -> pd.DataFrame:
    feed = KiteDataFeed()
    db = DB(DBConfig(sqlite_path=os.getenv("SQLITE_PATH", "data/trading.db")))
    store = InstrumentStore(db)
    store.ensure_cache(universe_csv=os.getenv("UNIVERSE", "data/universe_full_nse.csv"))
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    series = {}
    for sym in symbols:
        full = sym if sym.startswith("NSE:") else f"NSE:{sym}"
        try:
            token = store.token_for(full)
            df = feed.historical(token, start.isoformat(), end.isoformat(), "day")
            if df is None or df.empty:
                continue
            s = df.set_index("date")["close"].astype(float)
            s.name = sym.replace("NSE:", "")
            series[s.name] = s
        except Exception as exc:
            print(f"skip {sym}: {exc}", file=sys.stderr)
    if not series:
        raise SystemExit("No OHLC fetched — check Kite token")
    return pd.DataFrame(series).sort_index()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", default="INFY,TCS,RELIANCE,HDFCBANK,NIFTYBEES")
    p.add_argument("--universe-csv")
    p.add_argument("--top", type=int, default=0)
    p.add_argument("--days", type=int, default=400)
    p.add_argument("--budget", type=float, default=1000.0)
    args = p.parse_args()

    if args.universe_csv and args.top > 0:
        import csv

        syms = []
        with open(args.universe_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                syms.append(row.get("tradingsymbol") or row.get("symbol", ""))
                if len(syms) >= args.top:
                    break
        syms.append("NIFTYBEES")
    else:
        syms = [s.strip() for s in args.symbols.split(",") if s.strip()]

    panel = fetch_panel(syms, args.days)
    result = run_walk_forward(
        panel,
        BacktestConfig(daily_budget=args.budget),
    )
    print("=== BharatQuant Walk-Forward Backtest ===")
    for k, v in result.metrics.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    if not result.trades.empty:
        print(result.trades.tail(10).to_string(index=False))


if __name__ == "__main__":
    main()

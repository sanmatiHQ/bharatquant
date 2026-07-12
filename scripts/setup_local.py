#!/usr/bin/env python3.11
"""
Idempotent local bootstrap — DB, instruments, paper cash, bootstrap watchlist, Kite token check.

Usage (from repo root):
  set -a && source .env && set +a
  python3.11 scripts/setup_local.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
load_dotenv(ROOT / ".env")

from src.data.instruments import InstrumentStore
from src.data.sector_mapper import load_sector_map
from src.db.database import DB, DBConfig
from src.ops.healthchecks import check_db, check_token
from src.risk.event_calendar import seed_calendar_year

BOOTSTRAP_SYMBOLS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL",
    "ITC", "KOTAKBANK", "LT", "AXISBANK", "MARUTI", "BAJFINANCE", "HINDUNILVR",
    "ASIANPAINT", "TITAN", "SUNPHARMA", "WIPRO", "ULTRACEMCO", "NESTLEIND",
]


def _require_env(*keys: str) -> None:
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise SystemExit(f"Missing env: {', '.join(missing)}")


def _verify_kite_token() -> str:
    path = Path(os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json"))
    if not path.exists():
        raise SystemExit(f"No token file at {path} — run kite_auth --auto first")
    data = json.loads(path.read_text(encoding="utf-8"))
    token = data.get("access_token") or (data.get("data") or {}).get("access_token")
    if not token:
        raise SystemExit(f"No access_token in {path}")

    api_key = os.environ["KITE_API_KEY"]
    r = httpx.get(
        "https://api.kite.trade/user/profile",
        headers={"X-Kite-Version": "3", "Authorization": f"token {api_key}:{token}"},
        timeout=20,
    )
    if r.status_code != 200:
        raise SystemExit(f"Kite token invalid (HTTP {r.status_code}) — re-login required")
    user_id = r.json().get("data", {}).get("user_id", "?")
    print(f"Kite token OK — user_id={user_id}")
    return str(user_id)


def _seed_paper_cash(db: DB) -> None:
    if os.getenv("TRADING_MODE", "paper") != "paper":
        return
    row = db._conn.execute("SELECT IFNULL(SUM(delta),0) c FROM cash_ledger").fetchone()
    if float(row["c"]) != 0:
        print(f"Paper cash already seeded (balance delta={row['c']})")
        return
    seed = float(os.getenv("PAPER_STARTING_CASH", "10000"))
    db.add_cash(int(time.time()), seed, "paper_seed")
    print(f"Paper cash seeded: ₹{seed:,.0f}")


def _seed_bootstrap_screen(db: DB) -> None:
    cur = db._conn.execute("SELECT COUNT(*) c FROM screening_results").fetchone()
    if int(cur["c"]) > 0:
        print(f"Screening results exist ({cur['c']} rows) — skip bootstrap watchlist")
        return
    run_ts = int(time.time())
    cap = int(os.getenv("WS_WATCHLIST_SIZE", "200"))
    syms = BOOTSTRAP_SYMBOLS[:cap]
    with db.tx() as conn:
        for i, sym in enumerate(syms):
            score = 1.0 - (i * 0.01)
            conn.execute(
                """
                INSERT OR REPLACE INTO screening_results(run_ts, symbol, momentum_score)
                VALUES (?,?,?)
                """,
                (run_ts, sym, score),
            )
    print(f"Bootstrap watchlist seeded: {len(syms)} symbols")


def main() -> None:
    _require_env("KITE_API_KEY", "KITE_API_SECRET")
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "data").mkdir(exist_ok=True)

    print("=== BharatQuant local setup ===")
    _verify_kite_token()

    sqlite_path = os.getenv("SQLITE_PATH", "data/trading.db")
    universe = os.getenv("UNIVERSE", "data/universe_full_nse.csv")
    sector_csv = os.getenv("SECTOR_MAP_CSV", "data/sector_map.csv")

    db = DB(DBConfig(sqlite_path=sqlite_path))
    print(f"SQLite OK: {sqlite_path}")

    store = InstrumentStore(db)
    n = store.cache_from_universe_csv(universe)
    print(f"Instrument cache from universe: {n} rows")

    _seed_paper_cash(db)
    seed_calendar_year(db)
    load_sector_map(db, sector_csv)
    _seed_bootstrap_screen(db)

    from src.ops.agent_state import persist_context
    from src.strategies.base import MarketContext

    persist_context(db, MarketContext(regime="NEUTRAL"))

    inst_count = db._conn.execute("SELECT COUNT(*) c FROM instruments").fetchone()["c"]
    print(f"Instruments in DB: {inst_count}")
    print(f"check_token: {check_token()}")
    print(f"check_db: {check_db()}")
    print("=== Setup complete ===")
    print("Start stack: bash src/ops/start_system.sh")
    print("Dashboard:   http://127.0.0.1:8080")


if __name__ == "__main__":
    main()

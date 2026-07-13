"""Pre-open / startup full-universe screening orchestration."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Callable, Optional

from ..db.database import DB
from ..portfolio.allocation import build_from_screen
from ..screening.momentum_screener import MomentumScreener, ScreenerConfig

logger = logging.getLogger("bharatquant.screen_orchestrator")


def is_bootstrap_screen(db: DB) -> bool:
    """Detect placeholder large-cap list (1.0, 0.99, 0.98…) vs real momentum screen."""
    row = db._conn.execute("SELECT MAX(run_ts) AS ts FROM screening_results").fetchone()
    if not row or not row["ts"]:
        return True
    run_ts = int(row["ts"])
    rows = db._conn.execute(
        "SELECT symbol, momentum_score FROM screening_results WHERE run_ts=? ORDER BY momentum_score DESC",
        (run_ts,),
    ).fetchall()
    if len(rows) < 40:
        return True
    scores = [float(r["momentum_score"]) for r in rows[:8]]
    if len(scores) >= 3:
        diffs = [round(scores[i] - scores[i + 1], 4) for i in range(min(5, len(scores) - 1))]
        if all(0.009 <= d <= 0.011 for d in diffs[:3]):
            return True
    return False


def screen_stale_hours(db: DB, max_age_h: float = 20.0) -> bool:
    row = db._conn.execute("SELECT MAX(run_ts) AS ts FROM screening_results").fetchone()
    if not row or not row["ts"]:
        return True
    return (time.time() - int(row["ts"])) > max_age_h * 3600


async def run_full_screen(
    db: DB,
    universe_csv: str,
    logs_dir: str,
    *,
    reason: str = "manual",
    on_complete: Optional[Callable[[], None]] = None,
) -> dict:
    """Screen full NSE universe — parallel OHLC, persist hits, rebuild allocation."""
    min_score = float(os.getenv("MIN_SCORE", "0.65"))
    scr = MomentumScreener(
        ScreenerConfig(universe_csv=universe_csv, min_score=min_score, logs_dir=logs_dir),
        db,
    )
    logger.info("full_screen_start", extra={"reason": reason, "universe": universe_csv})
    df = await asyncio.to_thread(scr.run)
    alloc_n = 0
    if not df.empty:
        alloc = await asyncio.to_thread(build_from_screen, db, df)
        alloc_n = len(alloc)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("last_screen_source", reason),
        )
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("last_screen_ts", str(int(time.time()))),
        )
    if on_complete:
        on_complete()
    logger.info(
        "full_screen_done",
        extra={"reason": reason, "hits": len(df), "allocated": alloc_n},
    )
    return {"hits": len(df), "allocated": alloc_n, "reason": reason}


async def ensure_fresh_screen(
    db: DB,
    universe_csv: str,
    logs_dir: str,
    on_complete: Optional[Callable[[], None]] = None,
) -> None:
    """Run full screen if bootstrap placeholder or stale."""
    if is_bootstrap_screen(db) or screen_stale_hours(db):
        await run_full_screen(
            db,
            universe_csv,
            logs_dir,
            reason="bootstrap_or_stale",
            on_complete=on_complete,
        )

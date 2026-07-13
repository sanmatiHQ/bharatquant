"""Live market pulse — tick stats for dashboard (reads tick_log + settings)."""
from __future__ import annotations

import json
import os
import time
from typing import Any

from ..db.database import DB
from ..ops.healthchecks import check_token
from ..strategies.registry import strategy_count


def _get_setting(db: DB, key: str) -> str | None:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    return str(row["v"]) if row else None


def load_live_pulse(db: DB) -> dict[str, Any]:
    now = int(time.time())
    window_60 = now - 60
    window_300 = now - 300
    today_start = now - (now % 86400)

    ticks_1m = db._conn.execute(
        "SELECT COUNT(*) c FROM tick_log WHERE ts >= ?", (window_60,)
    ).fetchone()["c"]
    ticks_5m = db._conn.execute(
        "SELECT COUNT(*) c FROM tick_log WHERE ts >= ?", (window_300,)
    ).fetchone()["c"]
    ticks_today = db._conn.execute(
        "SELECT COUNT(*) c FROM tick_log WHERE ts >= ?", (today_start,)
    ).fetchone()["c"]

    last_tick = db._conn.execute(
        "SELECT ts, symbol, ltp FROM tick_log ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    last_tick_age = (now - int(last_tick["ts"])) if last_tick else None

    tape = [
        dict(r)
        for r in db._conn.execute(
            """
            SELECT ts, symbol, ltp FROM tick_log
            ORDER BY ts DESC LIMIT 25
            """
        ).fetchall()
    ]

    live_quotes = [
        dict(r)
        for r in db._conn.execute(
            """
            SELECT symbol, ltp, MAX(ts) AS ts
            FROM tick_log WHERE ts >= ?
            GROUP BY symbol ORDER BY ts DESC LIMIT 20
            """,
            (window_300,),
        ).fetchall()
    ]

    bars_5m = db._conn.execute(
        "SELECT COUNT(*) c FROM bar_log WHERE interval='5m' AND ts >= ?",
        (today_start,),
    ).fetchone()["c"]

    signals = db._conn.execute("SELECT COUNT(*) c FROM strategy_ledger").fetchone()["c"]
    trades = db._conn.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"]
    positions = db._conn.execute(
        "SELECT COUNT(*) c FROM positions WHERE qty > 0"
    ).fetchone()["c"]

    hb = _get_setting(db, "engine_heartbeat_ts")
    hb_age = now - int(hb) if hb and hb.isdigit() else None

    ws_live = (
        last_tick_age is not None
        and last_tick_age < 15
        and check_token(live=True)
        and hb_age is not None
        and hb_age < 90
    )

    narrative = _build_narrative(
        ws_live=ws_live,
        ticks_1m=int(ticks_1m),
        ticks_5m=int(ticks_5m),
        signals=int(signals),
        trades=int(trades),
        positions=int(positions),
        bars_5m=int(bars_5m),
        last_tick_age=last_tick_age,
    )

    return {
        "ws_live": ws_live,
        "kite_token_valid": check_token(live=True),
        "ticks_per_min": int(ticks_1m),
        "ticks_5m": int(ticks_5m),
        "ticks_today": int(ticks_today),
        "bars_5m_today": int(bars_5m),
        "symbols_streaming": len(live_quotes),
        "last_tick": dict(last_tick) if last_tick else None,
        "last_tick_age_sec": last_tick_age,
        "engine_heartbeat_age_sec": hb_age,
        "tape": tape,
        "live_quotes": live_quotes,
        "signals_total": int(signals),
        "trades_total": int(trades),
        "open_positions": int(positions),
        "narrative": narrative,
        "ts": now,
    }


def _build_narrative(
    *,
    ws_live: bool,
    ticks_1m: int,
    ticks_5m: int,
    signals: int,
    trades: int,
    positions: int,
    bars_5m: int,
    last_tick_age: int | None,
) -> str:
    if not check_token(live=False):
        return "Kite token missing — login required before market data."
    if not check_token(live=True):
        return "Kite token expired — click Login. Bot cannot read live prices until refreshed."
    if last_tick_age is None or last_tick_age > 60:
        return (
            "Engine running but no live ticks in the last minute. "
            "WebSocket may be reconnecting — check Kite login or market hours."
        )
    if ws_live and signals == 0:
        return (
            f"LIVE: {ticks_1m} ticks/min from Kite WebSocket on {ticks_5m} ticks in 5m. "
            f"Bot is scanning {strategy_count()}+ strategies on each tick/bar. "
            f"No trade signal yet — needs threshold hit (e.g. VWAP ±1.5%, 5m momentum bar, ORB break). "
            f"5m bars closed today: {bars_5m}."
        )
    if signals > 0 and trades == 0:
        return (
            f"Market data LIVE ({ticks_1m}/min). {signals} signals generated; "
            "risk/allocation may have vetoed execution — see Recent signals."
        )
    if positions > 0:
        return (
            f"LIVE ({ticks_1m} ticks/min). {positions} open position(s), "
            f"{trades} trades today. Monitoring stop-loss / take-profit on every tick."
        )
    return f"Market data LIVE — {ticks_1m} ticks/min. {trades} trades executed today."

"""Persist in-memory agent context for dashboard (Rule 23 — single snapshot key)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ..db.database import DB


def _set(db: DB, key: str, value: str) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (key, value),
        )


def _get(db: DB, key: str) -> str | None:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    return str(row["v"]) if row else None


def persist_context(db: DB, ctx: Any) -> None:
    snap = {
        "regime": getattr(ctx, "regime", "NEUTRAL"),
        "fii_net_cr": getattr(ctx, "fii_net_cr", 0),
        "dii_net_cr": getattr(ctx, "dii_net_cr", 0),
        "gift_nifty_change_pct": getattr(ctx, "gift_nifty_change_pct", 0),
        "india_vix": getattr(ctx, "india_vix", 0),
        "updated_ts": int(time.time()),
    }
    _set(db, "agent_context", json.dumps(snap))


def persist_decision(db: DB, decision: dict) -> None:
    decision["ts"] = int(time.time())
    _set(db, "agent_last_decision", json.dumps(decision, default=str))


def touch_heartbeat(db: DB) -> None:
    _set(db, "engine_heartbeat_ts", str(int(time.time())))


def load_agent_status(db: DB) -> dict:
    ctx_raw = _get(db, "agent_context")
    dec_raw = _get(db, "agent_last_decision")
    hb = _get(db, "engine_heartbeat_ts")
    try:
        ctx = json.loads(ctx_raw) if ctx_raw else {}
    except json.JSONDecodeError:
        ctx = {}
    try:
        last_decision = json.loads(dec_raw) if dec_raw else None
    except json.JSONDecodeError:
        last_decision = None

    cur = db._conn.execute(
        """
        SELECT symbol, momentum_score FROM screening_results
        WHERE run_ts = (SELECT MAX(run_ts) FROM screening_results)
        ORDER BY momentum_score DESC LIMIT 15
        """
    )
    watchlist = [dict(r) for r in cur.fetchall()]

    cur = db._conn.execute(
        "SELECT strategy_id, realized_pnl, trade_count FROM strategy_pnl ORDER BY trade_count DESC LIMIT 20"
    )
    strategy_stats = [dict(r) for r in cur.fetchall()]

    cur = db._conn.execute(
        """
        SELECT source, event_type, ts, execution_allowed FROM ingest_log
        ORDER BY ts DESC LIMIT 12
        """
    )
    ingest = [dict(r) for r in cur.fetchall()]

    enabled = 0
    try:
        import os
        import yaml

        cfg_path = os.getenv("CONFIG_YAML", "config.yaml")
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding="utf-8") as f:
                enabled = len((yaml.safe_load(f) or {}).get("strategies", {}).get("enabled", []))
    except Exception:
        enabled = 17

    return {
        "context": ctx,
        "last_decision": last_decision,
        "engine_heartbeat_ts": int(hb) if hb and hb.isdigit() else None,
        "supervisor_state": _get(db, "supervisor_state"),
        "supervisor_reason": _get(db, "supervisor_reason"),
        "rl_version": os.getenv("RL_ACTIVE_VERSION", "ppo_v1"),
        "rl_policy_exists": Path(os.getenv("RL_MODEL_DIR", "models/rl")).joinpath(
            os.getenv("RL_ACTIVE_VERSION", "ppo_v1"), "policy.npz"
        ).exists(),
        "watchlist": watchlist,
        "strategy_stats": strategy_stats,
        "ingest_feeds": ingest,
        "strategies_enabled": enabled,
        "signals_total": db._conn.execute("SELECT COUNT(*) c FROM strategy_ledger").fetchone()["c"],
        "shadow_total": db._conn.execute("SELECT COUNT(*) c FROM shadow_trades").fetchone()["c"],
    }

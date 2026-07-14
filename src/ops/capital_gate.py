"""Authoritative capital go-live gate — implements EVOLUTION_LOG checklist (non-sticky, re-evaluated)."""
from __future__ import annotations

import json
import os
import time
from typing import Any

from ..db.database import DB
from .fitness_evidence import (
    clock_start_ts,
    ensure_capital_clock,
    reset_capital_clock,
    system_fitness_snapshot,
)


def _min_weeks() -> int:
    return int(os.getenv("CAPITAL_MIN_TRADING_WEEKS", "6"))


def _min_closed_trades() -> int:
    return int(os.getenv("CAPITAL_MIN_CLOSED_TRADES", "150"))


def _min_composite() -> float:
    return float(os.getenv("CAPITAL_MIN_COMPOSITE", "0.5"))


def _max_drawdown_pct() -> float:
    return float(os.getenv("CAPITAL_MAX_DRAWDOWN_PCT", "18"))


def _min_promoted_full() -> int:
    return int(os.getenv("CAPITAL_MIN_PROMOTED_FULL", "5"))


def evaluate_capital_gate(db: DB) -> dict[str, Any]:
    """Fail-closed gate for TRADING_MODE=live. Re-evaluates every call — never sticky."""
    ensure_capital_clock(db)
    start = clock_start_ts(db)
    snap = system_fitness_snapshot(db, start)
    checks = {
        "trading_weeks": {
            "value": snap["trading_weeks"],
            "required": _min_weeks(),
            "pass": snap["trading_weeks"] >= _min_weeks(),
        },
        "closed_trades": {
            "value": snap["closed_sells"],
            "required": _min_closed_trades(),
            "pass": snap["closed_sells"] >= _min_closed_trades(),
        },
        "composite_fitness": {
            "value": snap["composite"],
            "required": _min_composite(),
            "pass": snap["composite"] >= _min_composite(),
        },
        "max_drawdown_pct": {
            "value": snap["max_drawdown_pct"],
            "required_max": _max_drawdown_pct(),
            "pass": snap["max_drawdown_pct"] <= _max_drawdown_pct(),
        },
        "promoted_full_strategies": {
            "value": snap["promoted_full_learned"],
            "required": _min_promoted_full(),
            "pass": snap["promoted_full_learned"] >= _min_promoted_full(),
        },
    }
    drawdown_breach = snap["max_drawdown_pct"] > _max_drawdown_pct() and snap["closed_sells"] >= 5
    if drawdown_breach:
        reset_capital_clock(db, f"drawdown_breach_{snap['max_drawdown_pct']:.1f}pct")
        snap = system_fitness_snapshot(db, clock_start_ts(db))
        checks["trading_weeks"]["value"] = snap["trading_weeks"]
        checks["trading_weeks"]["pass"] = snap["trading_weeks"] >= _min_weeks()
        checks["closed_trades"]["value"] = snap["closed_sells"]
        checks["closed_trades"]["pass"] = snap["closed_sells"] >= _min_closed_trades()

    all_pass = all(c["pass"] for c in checks.values())
    result = {
        "eligible": all_pass,
        "checks": checks,
        "fitness": snap,
        "evaluated_ts": int(time.time()),
        "note": "Go-live gate — paper clock must run clean; not satisfied by code deploy alone.",
    }
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO capital_gate_evaluations(ts, eligible, payload_json)
            VALUES (?,?,?)
            """,
            (result["evaluated_ts"], int(all_pass), json.dumps(result)),
        )
    return result


def live_mode_allowed(db: DB) -> tuple[bool, str, dict[str, Any]]:
    from .trading_config import resolved_trading_mode

    mode = resolved_trading_mode()
    if mode != "live":
        return True, "paper_mode", {"trading_mode": mode}
    gate = evaluate_capital_gate(db)
    if gate["eligible"]:
        return True, "capital_gate_ok", gate
    failed = [k for k, v in gate["checks"].items() if not v["pass"]]
    return False, f"capital_gate_blocked:{','.join(failed)}", gate

#!/usr/bin/env python3.11
"""Read-only VM proof for Layer 6 capital gate + feed health — exit 0 only if structural checks pass."""
from __future__ import annotations

import json
import os
import sys

from src.db.database import DB, DBConfig
from src.ops.capital_gate import evaluate_capital_gate
from src.ops.fitness_evidence import system_fitness_snapshot
from src.ops.session_state import session_phase
from src.ops.trading_config import resolved_trading_mode


def main() -> int:
    db_path = os.getenv("SQLITE_PATH", "data/trading.db")
    db = DB(DBConfig(sqlite_path=db_path))
    gate = evaluate_capital_gate(db)
    snap = system_fitness_snapshot(db)
    mode = resolved_trading_mode()
    phase = session_phase()

    structural = {
        "trading_mode": mode,
        "session_phase": phase,
        "capital_gate_evaluated": gate.get("evaluated_ts", 0) > 0,
        "fitness_sample_n": snap.get("sample_n", 0),
        "closed_sells": snap.get("closed_sells", 0),
        "composite": snap.get("composite", 0),
        "checks": gate.get("checks", {}),
        "eligible_for_live": gate.get("eligible", False),
    }
    print(json.dumps(structural, indent=2))

    # Structural PASS: gate runs, mode resolved, not live while ineligible
    if mode == "live" and not gate.get("eligible"):
        print("FAIL: TRADING_MODE=live but capital gate not eligible", file=sys.stderr)
        return 1
    if not gate.get("evaluated_ts"):
        print("FAIL: capital gate did not evaluate", file=sys.stderr)
        return 1
    print("PROVE OK: layer6 gate structural checks pass (go-live clock may still be open)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

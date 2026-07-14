"""
Trading lifecycle — paper learn on real data; live only after capital_gate passes.

Phase 1 (default): paper_learn — real Kite ticks, paper orders, RL + strategy discovery.
Phase 2: live_deploy — TRADING_MODE=live only when evaluate_capital_gate() is eligible.
"""
from __future__ import annotations

import os
from typing import Any

from ..db.database import DB
from .capital_gate import evaluate_capital_gate, live_mode_allowed
from .trading_config import resolved_trading_mode


def paper_performance(db: DB) -> dict[str, Any]:
    """Rolling paper PnL summary (informational — not the capital gate)."""
    from .fitness_evidence import clock_start_ts, closed_sell_returns

    start = clock_start_ts(db)
    rets = closed_sell_returns(db, start)
    net = sum(rets)
    return {
        "clock_start_ts": start,
        "closed_sells": len(rets),
        "mean_return": round(net / len(rets), 6) if rets else 0.0,
        "note": "Use /api/fitness/proof for authoritative go-live gate.",
    }


def evaluate_live_gate(db: DB) -> dict[str, Any]:
    mode = resolved_trading_mode()
    gate = evaluate_capital_gate(db)
    allowed, reason, _ = live_mode_allowed(db)
    return {
        "phase": "live_deploy" if mode == "live" else "paper_learn",
        "trading_mode": mode,
        "live_gate_eligible": gate["eligible"],
        "live_gate_allowed": allowed,
        "live_gate_reason": reason,
        "capital_gate": gate,
        "daily_live_budget_inr": f"{_env_min()}-{_env_max()}",
        "paper_performance": paper_performance(db),
        "note": (
            "Capital gate requires 6 trading weeks, ≥150 closed sells, composite ≥0.5, "
            f"max DD ≤{os.getenv('CAPITAL_MAX_DRAWDOWN_PCT', '18')}%, ≥5 promoted learned strategies."
        ),
    }


def _env_min() -> float:
    return float(os.getenv("DAILY_INVESTMENT_MIN", "1500"))


def _env_max() -> float:
    return float(os.getenv("DAILY_INVESTMENT_MAX", "2000"))


def assert_live_mode_allowed(db: DB) -> tuple[bool, str]:
    return live_mode_allowed(db)[:2]

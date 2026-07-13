"""
Trading lifecycle — paper learn on real data now; live ₹1500–2000/day after profitability gate.

Phase 1 (default): paper_learn — real Kite ticks, paper orders, RL + strategy discovery.
Phase 2 (manual): live_deploy — set TRADING_MODE=live after live_gate_eligible is true.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from ..db.database import DB


def _gate_min_return_pct() -> float:
    return float(os.getenv("LIVE_GATE_MIN_PAPER_RETURN_PCT", "5"))


def _gate_min_trades() -> int:
    return int(os.getenv("LIVE_GATE_MIN_TRADE_COUNT", "20"))


def _gate_lookback_days() -> int:
    return int(os.getenv("LIVE_GATE_LOOKBACK_DAYS", "30"))


def _get_setting(db: DB, key: str) -> str | None:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    return str(row["v"]) if row else None


def _set_setting(db: DB, key: str, value: str) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (key, value),
        )


def paper_performance(db: DB) -> dict[str, Any]:
    """Rolling paper PnL for live-gate evaluation."""
    cutoff = int(time.time()) - _gate_lookback_days() * 86400
    row = db._conn.execute(
        """
        SELECT
          IFNULL(SUM(CASE WHEN side='SELL' THEN amount ELSE 0 END),0)
          - IFNULL(SUM(CASE WHEN side='BUY' THEN amount ELSE 0 END),0) AS net_pnl,
          COUNT(*) AS trade_count
        FROM trades WHERE ts >= ?
        """,
        (cutoff,),
    ).fetchone()
    deployed = float(
        db._conn.execute(
            "SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY' AND ts >= ?",
            (cutoff,),
        ).fetchone()[0]
    )
    net = float(row["net_pnl"] or 0)
    trades = int(row["trade_count"] or 0)
    ret_pct = (net / deployed * 100) if deployed > 0 else 0.0
    return {
        "lookback_days": _gate_lookback_days(),
        "net_pnl_inr": round(net, 2),
        "deployed_inr": round(deployed, 2),
        "return_pct": round(ret_pct, 2),
        "trade_count": trades,
    }


def evaluate_live_gate(db: DB) -> dict[str, Any]:
    perf = paper_performance(db)
    eligible = (
        perf["trade_count"] >= _gate_min_trades()
        and perf["return_pct"] >= _gate_min_return_pct()
    )
    if eligible:
        _set_setting(db, "live_gate_eligible", "true")
    mode = os.getenv("TRADING_MODE", "paper")
    phase = "live_deploy" if mode == "live" else "paper_learn"
    return {
        "phase": phase,
        "trading_mode": mode,
        "live_gate_eligible": _get_setting(db, "live_gate_eligible") == "true" or eligible,
        "live_gate_threshold_return_pct": _gate_min_return_pct(),
        "live_gate_threshold_trades": _gate_min_trades(),
        "daily_live_budget_inr": f"{_env_min()}-{_env_max()}",
        "paper_performance": perf,
        "note": (
            "Paper learn on real market data until profitability gate clears; "
            "then deploy ₹1500–2000/day real Zerodha capital (TRADING_MODE=live)."
        ),
    }


def _env_min() -> float:
    return float(os.getenv("DAILY_INVESTMENT_MIN", "1500"))


def _env_max() -> float:
    return float(os.getenv("DAILY_INVESTMENT_MAX", "2000"))


def assert_live_mode_allowed(db: DB) -> tuple[bool, str]:
    """Block accidental live mode before profitability demonstrated."""
    if os.getenv("TRADING_MODE", "paper") != "live":
        return True, "paper"
    status = evaluate_live_gate(db)
    if status["live_gate_eligible"]:
        return True, "live_gate_ok"
    return False, "live_gate_not_met_set_TRADING_MODE=paper"

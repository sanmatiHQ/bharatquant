"""Structured loss root-cause tags for demotion and review."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from ..db.database import DB


def record_closed_loss(
    db: DB,
    *,
    trade_id: Optional[int],
    symbol: str,
    strategy_id: str,
    pnl_inr: float,
    regime_entry: str,
    regime_exit: str,
    stop_designed: bool,
    stop_slipped: bool,
    slippage_inr: float,
    slippage_bps: float,
    signal_failure_pct: float,
    cost_drag_pct: float,
    meta: Optional[dict[str, Any]] = None,
) -> None:
    if pnl_inr >= 0:
        return
    structural = signal_failure_pct >= 60.0 or (stop_designed and stop_slipped)
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO loss_ledger(
              ts, trade_id, symbol, strategy_id, pnl_inr,
              regime_entry, regime_exit, stop_designed, stop_slipped,
              slippage_inr, slippage_bps, signal_failure_pct, cost_drag_pct,
              structural_failure, meta_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                int(time.time()),
                trade_id,
                symbol.replace("NSE:", ""),
                strategy_id,
                pnl_inr,
                regime_entry,
                regime_exit,
                int(stop_designed),
                int(stop_slipped),
                slippage_inr,
                slippage_bps,
                signal_failure_pct,
                cost_drag_pct,
                int(structural),
                json.dumps(meta or {}),
            ),
        )


def structural_loss_count(db: DB, strategy_id: str, *, days: int = 30) -> int:
    cutoff = int(time.time()) - days * 86400
    row = db._conn.execute(
        """
        SELECT COUNT(*) n FROM loss_ledger
        WHERE strategy_id=? AND ts>=? AND structural_failure=1
        """,
        (strategy_id, cutoff),
    ).fetchone()
    return int(row["n"] or 0)


def recent_losses(db: DB, strategy_id: str, limit: int = 20) -> list[dict]:
    rows = db._conn.execute(
        """
        SELECT * FROM loss_ledger WHERE strategy_id=? ORDER BY ts DESC LIMIT ?
        """,
        (strategy_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]

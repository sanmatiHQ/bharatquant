"""Paired predicted vs actual execution — running signed bias for live/paper parity."""
from __future__ import annotations

import os
import time
from typing import Any, Optional

from ..db.database import DB


def record_slippage_pair(
    db: DB,
    *,
    symbol: str,
    side: str,
    predicted_price: float,
    actual_price: float,
    qty: int,
    strategy_id: str = "",
    source: str = "paper",
) -> dict[str, Any]:
    if predicted_price <= 0 or qty <= 0:
        return {"ok": False}
    signed_bps = (actual_price - predicted_price) / predicted_price * 10_000.0
    if side.upper() == "SELL":
        signed_bps = -signed_bps
    slip_inr = (actual_price - predicted_price) * qty
    if side.upper() == "SELL":
        slip_inr = -slip_inr
    ts = int(time.time())
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO slippage_parity(
              ts, symbol, side, qty, predicted_price, actual_price,
              signed_bps, slippage_inr, strategy_id, source
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (ts, symbol.replace("NSE:", ""), side.upper(), qty, predicted_price, actual_price, signed_bps, slip_inr, strategy_id, source),
        )
    return {"ok": True, "signed_bps": signed_bps, "slippage_inr": slip_inr}


def running_bias(db: DB, *, lookback: int = 100) -> dict[str, Any]:
    rows = db._conn.execute(
        """
        SELECT signed_bps, slippage_inr, source FROM slippage_parity
        ORDER BY ts DESC LIMIT ?
        """,
        (lookback,),
    ).fetchall()
    if not rows:
        return {"n": 0, "mean_signed_bps": 0.0, "total_inr": 0.0, "drift_alert": False}
    bps = [float(r["signed_bps"]) for r in rows]
    mean_bps = sum(bps) / len(bps)
    total_inr = sum(float(r["slippage_inr"]) for r in rows)
    threshold = float(os.getenv("SLIPPAGE_BIAS_ALERT_BPS", "8"))
    return {
        "n": len(rows),
        "mean_signed_bps": round(mean_bps, 2),
        "total_inr": round(total_inr, 2),
        "drift_alert": abs(mean_bps) >= threshold,
        "threshold_bps": threshold,
    }

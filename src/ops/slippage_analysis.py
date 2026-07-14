"""Post-market slippage — compare execution LTP vs strategy signal price."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db.database import DB

IST = timezone(timedelta(hours=5, minutes=30))


def _today_start_ts() -> int:
    now = datetime.now(IST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def analyze_today_slippage(db: DB) -> dict[str, Any]:
    """Join today's fills with nearest executed strategy_ledger price as target."""
    today = _today_start_ts()
    trades = db._conn.execute(
        """
        SELECT id, ts, symbol, side, qty, price, reason
        FROM trades WHERE ts >= ? ORDER BY ts ASC
        """,
        (today,),
    ).fetchall()
    rows: list[dict] = []
    total_slip_inr = 0.0
    total_slip_bps = 0.0
    n = 0
    ctx_raw = db._conn.execute("SELECT v FROM settings WHERE k='agent_context'").fetchone()
    llm_bias = 0.0
    if ctx_raw:
        try:
            llm_bias = float(json.loads(ctx_raw["v"]).get("llm_bias", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    for t in trades:
        sym = str(t["symbol"])
        leg = db._conn.execute(
            """
            SELECT price, ts, strategy_id FROM strategy_ledger
            WHERE symbol=? AND executed=1 AND ts <= ? AND price > 0
            ORDER BY ts DESC LIMIT 1
            """,
            (sym, int(t["ts"])),
        ).fetchone()
        target = float(leg["price"]) if leg else float(t["price"])
        exec_px = float(t["price"])
        slip_inr = (exec_px - target) * int(t["qty"])
        if t["side"] == "SELL":
            slip_inr = -slip_inr
        slip_bps = 0.0
        if target > 0:
            slip_bps = (exec_px - target) / target * 10_000
            if t["side"] == "SELL":
                slip_bps = -slip_bps
        total_slip_inr += slip_inr
        if target > 0:
            total_slip_bps += abs(slip_bps)
            n += 1
        rows.append(
            {
                "trade_id": t["id"],
                "ts": t["ts"],
                "symbol": sym,
                "side": t["side"],
                "qty": t["qty"],
                "execution_price": exec_px,
                "target_price": target,
                "slippage_inr": round(slip_inr, 2),
                "slippage_bps": round(slip_bps, 2),
                "strategy_id": leg["strategy_id"] if leg else None,
                "llm_bias_at_execution": llm_bias,
            }
        )
        from .slippage_parity import record_slippage_pair

        record_slippage_pair(
            db,
            symbol=sym,
            side=str(t["side"]),
            predicted_price=target,
            actual_price=exec_px,
            qty=int(t["qty"]),
            strategy_id=str(leg["strategy_id"]) if leg and leg["strategy_id"] else "",
            source="eod_reconcile",
        )

    summary = {
        "ts": int(time.time()),
        "trade_count": len(rows),
        "avg_abs_slippage_bps": round(total_slip_bps / n, 2) if n else 0.0,
        "total_slippage_inr": round(total_slip_inr, 2),
        "rows": rows,
    }
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("slippage_summary_latest", json.dumps(summary)),
        )
    return summary

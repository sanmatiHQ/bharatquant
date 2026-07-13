"""Panic halt — kill switch + flatten all paper positions immediately."""
from __future__ import annotations

import logging
import os
import time

from ..accounting.fifo_lots import close_lots_fifo
from ..costs.cost_engine import CostEngine
from ..db.database import DB
from ..exec.paper_broker import PaperBroker
from ..ops.kill_switch import set_halt

logger = logging.getLogger("bharatquant.panic_halt")


def panic_halt_and_squareoff(db: DB, *, reason: str = "panic_halt") -> dict:
    """Set halt flag and sell all open paper positions at last LTP."""
    set_halt(db, reason=reason)
    costs = CostEngine(slippage_bps=int(os.getenv("SLIPPAGE_BPS", "4")))
    paper = PaperBroker(slippage_bps=int(os.getenv("SLIPPAGE_BPS", "4")))
    ts = int(time.time())
    closed = 0
    proceeds = 0.0

    rows = db._conn.execute(
        "SELECT symbol, qty, last_price, avg_price, rail FROM positions WHERE qty > 0"
    ).fetchall()
    for row in rows:
        sym = str(row["symbol"])
        qty = int(row["qty"])
        ltp = float(row["last_price"] or row["avg_price"])
        if qty <= 0 or ltp <= 0:
            continue
        exec_px = paper.sell(sym, qty, ltp)
        fees = costs.compute_trade_costs(sym, qty, exec_px, "SELL", order_id=f"PANIC-{ts}")
        close_lots_fifo(db, sym, qty, exec_px, ts, costs)
        amount = exec_px * qty - fees
        db.record_trade(ts, sym, "SELL", qty, exec_px, amount, f"panic:{reason}", fees, "NA", order_id=f"PANIC-{ts}")
        db.add_cash(ts, amount, f"panic_sell:{sym}")
        closed += 1
        proceeds += amount
    logger.warning("panic_squareoff", extra={"closed": closed, "reason": reason})
    return {"halted": True, "reason": reason, "positions_closed": closed, "proceeds_inr": round(proceeds, 2)}

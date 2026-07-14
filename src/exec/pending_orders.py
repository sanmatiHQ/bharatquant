"""Live mode: book positions only after broker fill confirmation."""
from __future__ import annotations

import logging
import time

from ..accounting.fifo_lots import close_lots_fifo, open_lot
from ..costs.cost_engine import CostEngine
from ..db.database import DB
from ..ops.budget_gate import consume_rolled_on_deploy
from ..strategies.base import Signal

logger = logging.getLogger("bharatquant.pending_orders")


def record_pending(
    db: DB,
    *,
    order_id: str,
    symbol: str,
    side: str,
    qty: int,
    price: float,
    rail: str,
    strategy_id: str,
    reason: str,
) -> None:
    with db.tx() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO pending_orders
            (order_id, ts, symbol, side, qty, price, rail, strategy_id, reason, status)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (order_id, int(time.time()), symbol, side, qty, price, rail, strategy_id, reason, "PENDING"),
        )


def settle_pending_fill(
    db: DB,
    *,
    order_id: str,
    fill_price: float,
    qty: int,
    costs: CostEngine | None = None,
) -> bool:
    """Apply cash/position updates when ORDER_FILL arrives for a pending order."""
    row = db._conn.execute(
        "SELECT * FROM pending_orders WHERE order_id=? AND status='PENDING'",
        (order_id,),
    ).fetchone()
    if not row:
        return False

    sym = str(row["symbol"])
    side = str(row["side"]).upper()
    rail = str(row["rail"] or "MIS")
    ts = int(time.time())
    fees = 0.0
    if costs:
        fees = costs.compute_trade_costs(sym, qty, fill_price, side, order_id=order_id)

    if side == "BUY":
        amount = fill_price * qty + fees
        from ..ops.budget_gate import can_deploy

        ok_b, b_reason = can_deploy(db, amount)
        if not ok_b:
            logger.warning("pending_fill_budget_blocked", extra={"order_id": order_id, "reason": b_reason})
            return False
        tid = db.record_trade(ts, sym, "BUY", qty, fill_price, amount, row["reason"], fees, "NA", order_id=order_id)
        db.add_cash(ts, -amount, f"buy:{sym}")
        consume_rolled_on_deploy(db, amount)
        open_lot(db, sym, qty, fill_price, ts, rail, tid)
    else:
        fills, tax_class = close_lots_fifo(db, sym, qty, fill_price, ts, costs)
        proceeds = fill_price * qty - fees
        db.record_trade(ts, sym, "SELL", qty, fill_price, proceeds, row["reason"], fees, tax_class, order_id=order_id)
        db.add_cash(ts, proceeds, f"sell:{sym}")

    with db.tx() as conn:
        conn.execute("UPDATE pending_orders SET status='FILLED' WHERE order_id=?", (order_id,))
    logger.info("pending_order_settled", extra={"order_id": order_id, "symbol": sym, "side": side})
    return True

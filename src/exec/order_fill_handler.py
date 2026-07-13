"""ORDER_FILL reconciliation — sync broker fills to SQLite + settle pending orders."""
from __future__ import annotations

import logging
import time

from ..db.database import DB
from ..events.types import EventType, MarketEvent
from ..exec.pending_orders import settle_pending_fill
from ..costs.cost_engine import CostEngine

logger = logging.getLogger("bharatquant.order_fill")


async def on_order_fill(db: DB, event: MarketEvent) -> None:
    p = event.payload or {}
    order_id = str(p.get("order_id", ""))
    if not order_id:
        return
    sym = str(p.get("symbol", event.symbol)).replace("NSE:", "")
    fill_px = float(p.get("fill_price", event.price) or 0)
    qty = int(p.get("qty", 0))
    status = str(p.get("status", "COMPLETE")).upper()
    if status not in ("COMPLETE", "FILLED") or fill_px <= 0 or qty <= 0:
        return

    costs = CostEngine(slippage_bps=int(__import__("os").getenv("SLIPPAGE_BPS", "4")))
    if settle_pending_fill(db, order_id=order_id, fill_price=fill_px, qty=qty, costs=costs):
        logger.info("pending_fill_settled", extra={"order_id": order_id, "price": fill_px})
        return

    row = db._conn.execute(
        "SELECT id, price, qty FROM trades WHERE order_id=? ORDER BY id DESC LIMIT 1",
        (order_id,),
    ).fetchone()
    if row:
        with db.tx() as conn:
            conn.execute(
                "UPDATE trades SET price=?, amount=price*qty WHERE id=?",
                (fill_px, int(row["id"])),
            )
            conn.execute(
                "UPDATE positions SET last_price=?, avg_price=? WHERE symbol=?",
                (fill_px, fill_px, sym),
            )
        logger.info("order_fill_reconciled", extra={"order_id": order_id, "price": fill_px})
    else:
        side = str(p.get("side", "BUY")).upper()
        fees = float(p.get("fees", 0))
        amount = fill_px * qty + (fees if side == "BUY" else -fees)
        db.record_trade(
            int(time.time()),
            sym,
            side,
            qty,
            fill_px,
            amount,
            "order_fill",
            fees,
            "NA",
            order_id=order_id,
        )
        logger.info("order_fill_recorded", extra={"order_id": order_id, "symbol": sym})


def paper_fill_event(symbol: str, side: str, qty: int, price: float, order_id: str) -> MarketEvent:
    return MarketEvent(
        type=EventType.ORDER_FILL,
        symbol=symbol,
        price=price,
        payload={
            "order_id": order_id,
            "symbol": symbol.replace("NSE:", ""),
            "side": side,
            "qty": qty,
            "fill_price": price,
            "status": "COMPLETE",
        },
    )

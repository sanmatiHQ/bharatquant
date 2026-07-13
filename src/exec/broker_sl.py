"""Broker-side SL-M stop-loss backup for MIS entries."""
from __future__ import annotations

import logging
import os

from kiteconnect import KiteConnect

from ..strategies.base import Signal

logger = logging.getLogger("bharatquant.broker_sl")


def place_sl_m(
    kite: KiteConnect,
    signal: Signal,
    qty: int,
    entry_price: float,
    *,
    stop_pct: float | None = None,
) -> str | None:
    """Place exchange SL-M order as backup to software stop."""
    if os.getenv("BROKER_SL_ENABLED", "true").lower() not in ("1", "true", "yes"):
        return None
    if signal.rail.upper() != "MIS" or qty <= 0 or entry_price <= 0:
        return None
    pct = stop_pct or float(os.getenv("STOP_LOSS_PCT", "4"))
    trigger = round(entry_price * (1 - pct / 100.0), 2)
    sym = signal.symbol.replace("NSE:", "")
    try:
        oid = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange="NSE",
            tradingsymbol=sym,
            transaction_type=kite.TRANSACTION_TYPE_SELL,
            quantity=qty,
            product=kite.PRODUCT_MIS,
            order_type=kite.ORDER_TYPE_SLM,
            trigger_price=trigger,
        )
        logger.info("broker_sl_placed", extra={"symbol": sym, "trigger": trigger, "order_id": oid})
        return str(oid)
    except Exception:
        logger.exception("broker_sl_failed", extra={"symbol": sym})
        return None

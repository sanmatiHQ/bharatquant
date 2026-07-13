"""Agile limit order placement with bid chasing (live mode only)."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("bharatquant.limit_chase")


async def place_limit_with_chase(
    kite: Any,
    *,
    exchange: str,
    tradingsymbol: str,
    transaction_type: str,
    quantity: int,
    target_price: float,
    product: str,
    tag: str = "",
    max_attempts: int | None = None,
    wait_sec: float | None = None,
) -> Optional[str]:
    """
    Place LIMIT at target_price; if unfilled after wait_sec, cancel and re-quote at best bid.
    Returns order_id on fill, None on failure/timeout.
    """
    attempts = max_attempts or int(os.getenv("LIMIT_CHASE_ATTEMPTS", "3"))
    wait = wait_sec or float(os.getenv("LIMIT_CHASE_WAIT_SEC", "1.5"))
    variety = kite.VARIETY_REGULAR

    for attempt in range(attempts):
        try:
            oid = kite.place_order(
                variety=variety,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=product,
                order_type=kite.ORDER_TYPE_LIMIT,
                price=round(target_price, 2),
                validity=kite.VALIDITY_DAY,
                tag=tag[:20] if tag else "",
            )
            oid = str(oid)
        except Exception:
            logger.exception("limit_place_failed", extra={"symbol": tradingsymbol, "attempt": attempt})
            return None

        await asyncio.sleep(wait)
        try:
            history = kite.order_history(oid)
            status = history[-1]["status"] if history else "UNKNOWN"
            if status == "COMPLETE":
                logger.info("limit_chase_filled", extra={"order_id": oid, "attempt": attempt})
                return oid
            if status in ("CANCELLED", "REJECTED"):
                return None
            kite.cancel_order(variety=variety, order_id=oid)
        except Exception:
            logger.exception("limit_chase_poll_failed", extra={"order_id": oid})

        # Re-quote: for BUY use slightly higher limit toward LTP
        try:
            q = kite.quote(f"{exchange}:{tradingsymbol}")
            key = f"{exchange}:{tradingsymbol}"
            depth = q.get(key, {}).get("depth", {})
            bids = depth.get("buy") or []
            if bids and transaction_type == kite.TRANSACTION_TYPE_BUY:
                target_price = float(bids[0]["price"])
            elif bids and transaction_type == kite.TRANSACTION_TYPE_SELL:
                asks = depth.get("sell") or []
                if asks:
                    target_price = float(asks[0]["price"])
        except Exception:
            target_price *= 1.001 if transaction_type == "BUY" else 0.999

    logger.warning("limit_chase_exhausted", extra={"symbol": tradingsymbol})
    return None

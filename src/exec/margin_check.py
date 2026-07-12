"""Margin pre-check before live orders."""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger("bharatquant.margin")


def estimate_required_margin(symbol: str, qty: int, price: float, rail: str) -> float:
    """Conservative estimate when Kite margins API unavailable."""
    notional = qty * price
    rail = rail.upper()
    if rail == "MIS":
        return notional * 0.2
    if rail == "NRML":
        return notional * 0.15
    if rail == "OPT":
        return notional * 0.1
    return notional  # CNC full cash


def check_margin(
    *,
    symbol: str,
    qty: int,
    price: float,
    rail: str,
    available_cash: float,
    kite=None,
) -> Tuple[bool, str]:
    if os.getenv("TRADING_MODE", "paper") != "live":
        req = estimate_required_margin(symbol, qty, price, rail)
        if req > available_cash * 1.05:
            return False, "paper_insufficient_cash"
        return True, "ok"
    if kite is None:
        req = estimate_required_margin(symbol, qty, price, rail)
        if req > available_cash:
            return False, "margin_estimate_exceeded"
        return True, "ok"
    try:
        orders = [{
            "exchange": "NSE",
            "tradingsymbol": symbol.replace("NSE:", ""),
            "transaction_type": "BUY",
            "variety": "regular",
            "product": rail,
            "order_type": "MARKET",
            "quantity": qty,
        }]
        resp = kite.order_margins(orders)
        total = float(resp[0].get("total", 0)) if resp else 0
        if total > available_cash:
            return False, "kite_margin_insufficient"
        return True, "ok"
    except Exception:
        logger.exception("margin_api_failed")
        req = estimate_required_margin(symbol, qty, price, rail)
        if req > available_cash:
            return False, "margin_fallback_exceeded"
        return True, "ok_fallback"

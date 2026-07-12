"""Live Kite order placement — requires whitelisted static IP."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from kiteconnect import KiteConnect

from ..strategies.base import Signal
from ..utils.rate_limit import RateLimiter

logger = logging.getLogger("bharatquant.live_broker")


@dataclass
class LiveBrokerConfig:
    api_key: str
    access_token: str
    max_rupees_per_trade: float = 1000.0


class LiveBroker:
    def __init__(self, cfg: LiveBrokerConfig) -> None:
        self.cfg = cfg
        self._kite = KiteConnect(api_key=cfg.api_key)
        self._kite.set_access_token(cfg.access_token)
        # SEBI retail algo throttle — 10 orders/sec cap
        self._ops_limiter = RateLimiter(max_per_sec=10, max_per_min=300)

    def _product(self, rail: str) -> str:
        return {"CNC": "CNC", "MIS": "MIS", "NRML": "NRML", "OPT": "NRML"}.get(rail.upper(), "CNC")

    def _exchange(self, signal: Signal) -> str:
        if signal.rail.upper() == "OPT":
            return "NFO"
        return "NSE"

    def _transaction(self, action: str) -> str:
        return "BUY" if action.upper() in ("BUY", "HEDGE") else "SELL"

    def place(self, signal: Signal, ltp: float, qty: int) -> Optional[str]:
        if qty <= 0 or ltp <= 0:
            return None
        if not self._ops_limiter.allow():
            logger.warning("ops_throttle", extra={"symbol": signal.symbol})
            return None
        amount = ltp * qty
        if amount > self.cfg.max_rupees_per_trade:
            qty = max(1, int(self.cfg.max_rupees_per_trade // ltp))
        try:
            oid = self._kite.place_order(
                variety=self._kite.VARIETY_REGULAR,
                exchange=self._exchange(signal),
                tradingsymbol=signal.symbol.replace("NSE:", "").replace("NFO:", ""),
                transaction_type=self._transaction(signal.action),
                quantity=qty,
                product=self._product(signal.rail),
                order_type=self._kite.ORDER_TYPE_MARKET,
                validity=self._kite.VALIDITY_DAY,
                tag=signal.strategy_id[:20],
            )
            logger.info("order_placed", extra={"order_id": oid, "symbol": signal.symbol, "qty": qty})
            return str(oid)
        except Exception:
            logger.exception("order_failed", extra={"symbol": signal.symbol})
            return None


def broker_from_env() -> Optional[LiveBroker]:
    mode = os.getenv("TRADING_MODE", "paper")
    if mode != "live":
        return None
    api_key = os.getenv("KITE_API_KEY", "")
    from ..feeds.kite_ticker import load_access_token

    try:
        key, token = load_access_token()
        return LiveBroker(
            LiveBrokerConfig(
                api_key=key or api_key,
                access_token=token,
                max_rupees_per_trade=float(os.getenv("MAX_RUPEES_PER_TRADE", "1000")),
            )
        )
    except Exception:
        logger.exception("live_broker_init_failed")
        return None

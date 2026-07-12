"""
Cost and tax engine — Zerodha CNC model with rqalpha min-commission pattern.

Verified rqalpha StockTransactionCostDecider._calc_commission (deciders.py:55-85):
  max(per-order commission, min_commission) with order-level remainder map.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class CostEngine:
    slippage_bps: int
    min_commission_inr: float = 20.0
    commission_rate: float = 0.0003
    stt_sell_rate: float = 0.001
    _order_commission_left: Dict[str, float] = field(default_factory=dict)

    def apply_slippage(self, price: float, side: str) -> float:
        bps = self.slippage_bps / 10_000.0
        if side.upper() == "BUY":
            return price * (1.0 + bps)
        return price * (1.0 - bps)

    def _calc_commission(self, turnover: float, order_id: str | None) -> float:
        raw = turnover * self.commission_rate
        if order_id is None:
            return max(raw, self.min_commission_inr)
        remaining = self._order_commission_left.get(order_id, self.min_commission_inr)
        if raw > remaining:
            if remaining == self.min_commission_inr:
                self._order_commission_left[order_id] = 0.0
                return raw
            self._order_commission_left[order_id] = 0.0
            return raw - remaining
        if remaining == self.min_commission_inr:
            self._order_commission_left[order_id] = remaining - raw
            return self.min_commission_inr
        self._order_commission_left[order_id] = remaining - raw
        return 0.0

    def compute_trade_costs(
        self,
        symbol: str,
        qty: int,
        price: float,
        side: str,
        ts: int | None = None,
        order_id: str | None = None,
    ) -> float:
        """Brokerage + STT + statutory — returns positive fee total."""
        turnover = price * qty
        brokerage = self._calc_commission(turnover, order_id)
        stt = turnover * self.stt_sell_rate if side.upper() == "SELL" else 0.0
        gst = 0.18 * brokerage
        sebi = 0.000001 * turnover
        stamp = 0.00003 * turnover if side.upper() == "BUY" else 0.0
        infra = 0.5
        return float(brokerage + stt + gst + sebi + stamp + infra)

    def classify_tax(self, hold_days: int) -> str:
        return "STCG" if hold_days < 365 else "LTCG"

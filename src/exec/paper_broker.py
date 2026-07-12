"""
Deterministic paper broker: fills at LTP minus slippage haircut.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PaperBroker:
    slippage_bps: int

    def _apply_slippage(self, price: float, side: str) -> float:
        haircut = price * (self.slippage_bps / 10_000)
        return price - haircut if side.upper() == "BUY" else price + haircut

    def buy(self, symbol: str, qty: int, ltp: float) -> float:
        return self._apply_slippage(ltp, "BUY")

    def sell(self, symbol: str, qty: int, ltp: float) -> float:
        return self._apply_slippage(ltp, "SELL")

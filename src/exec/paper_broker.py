"""
Paper broker — fills through CostEngine (same slippage model as live cost path).
BUY fills above LTP, SELL below LTP (trader always pays spread).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..costs.cost_engine import CostEngine


@dataclass
class PaperBroker:
    slippage_bps: int
    _costs: CostEngine = field(init=False)

    def __post_init__(self) -> None:
        self._costs = CostEngine(slippage_bps=self.slippage_bps)

    def buy(self, symbol: str, qty: int, ltp: float) -> float:
        return self._costs.apply_slippage(ltp, "BUY")

    def sell(self, symbol: str, qty: int, ltp: float) -> float:
        return self._costs.apply_slippage(ltp, "SELL")

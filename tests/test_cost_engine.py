from __future__ import annotations
from src.costs.cost_engine import CostEngine


def test_costs_positive():
    ce = CostEngine(slippage_bps=4)
    fees = ce.compute_trade_costs('NSE:INFY', 10, 100.0, 'BUY')
    assert fees > 0


def test_min_commission_floor():
    ce = CostEngine(slippage_bps=0, min_commission_inr=20.0)
    fees = ce.compute_trade_costs('NSE:INFY', 1, 10.0, 'BUY')
    assert fees >= 20.0

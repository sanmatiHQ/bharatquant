"""Cost gate — block 1-share trades that cannot clear brokerage."""
from __future__ import annotations

import pytest

from src.costs.cost_engine import CostEngine
from src.ops.cost_gate import min_qty_for_cost_edge, passes_cost_gate, round_trip_cost_pct


def test_one_share_blocked_for_expensive_stock():
    costs = CostEngine(slippage_bps=4, min_commission_inr=20.0)
    assert min_qty_for_cost_edge(costs, 1100.0, 2000.0) == 0


def test_multi_share_allowed_on_midcap():
    costs = CostEngine(slippage_bps=4, min_commission_inr=20.0)
    q = min_qty_for_cost_edge(costs, 150.0, 2000.0)
    assert q >= 10
    assert round_trip_cost_pct(costs, q, 150.0) <= 3.5


def test_passes_cost_gate_when_edge_sufficient():
    costs = CostEngine(slippage_bps=4)
    assert passes_cost_gate(costs, 150.0, 15, 3.0) is True

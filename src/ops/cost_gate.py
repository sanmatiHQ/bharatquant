"""Block trades where round-trip brokerage exceeds realistic edge."""
from __future__ import annotations

import os

from ..costs.cost_engine import CostEngine


def round_trip_cost_pct(costs: CostEngine, qty: int, ltp: float) -> float:
    turnover = qty * ltp
    if turnover <= 0:
        return 100.0
    return costs.round_trip_cost_inr(qty, ltp) / turnover * 100.0


def min_qty_for_cost_edge(
    costs: CostEngine,
    ltp: float,
    deploy_cap_inr: float,
    *,
    max_cost_pct: float | None = None,
) -> int:
    """
    Smallest whole-share qty where round-trip fee drag is below threshold.
    Blocks 1-share ₹1100 trades (~5% fee drag); allows 10+ shares on ₹150 names.
    """
    if ltp <= 0 or deploy_cap_inr < ltp:
        return 0
    limit = max_cost_pct if max_cost_pct is not None else float(os.getenv("COST_MAX_ROUNDTRIP_PCT", "3.5"))
    max_q = int(deploy_cap_inr // ltp)
    for qty in range(1, max_q + 1):
        if round_trip_cost_pct(costs, qty, ltp) <= limit:
            return qty
    return 0


def passes_cost_gate(costs: CostEngine, ltp: float, qty: int, expected_move_pct: float) -> bool:
    if qty <= 0 or ltp <= 0:
        return False
    need = costs.min_profit_move_pct(qty, ltp)
    return expected_move_pct >= need

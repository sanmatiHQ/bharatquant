"""Action masking — RL cannot emit buy when unaffordable."""
from __future__ import annotations

import numpy as np

from ..ops.budget_gate import remaining_budget
from ..ops.trade_sizing import can_buy_whole_share, deploy_cap_inr
from ..db.database import DB

N_ACTIONS = 3  # hold=0, buy=1, sell=2


def masked_action_probs(
    probs: np.ndarray,
    *,
    cash: float,
    ltp: float,
    db: DB | None,
    has_position: bool,
) -> np.ndarray:
    """Zero invalid actions then renormalize."""
    p = np.array(probs, dtype=np.float64).copy()
    if ltp > 0 and db is not None:
        cap = deploy_cap_inr(db, cash)
        if not can_buy_whole_share(ltp, cap):
            p[1] = 0.0
    elif ltp > 0 and cash < ltp:
        p[1] = 0.0
    if not has_position:
        p[2] = 0.0
    if p.sum() <= 0:
        return np.array([1.0, 0.0, 0.0])
    return p / p.sum()


def is_buy_allowed(cash: float, ltp: float, db: DB | None) -> bool:
    if ltp <= 0:
        return False
    if db is None:
        return cash >= ltp
    return can_buy_whole_share(ltp, deploy_cap_inr(db, cash)) and remaining_budget(db) >= ltp

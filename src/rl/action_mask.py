"""Action masking — RL cannot emit buy when unaffordable or drawdown halted."""
from __future__ import annotations

import os

import numpy as np

from ..ops.budget_gate import remaining_budget
from ..ops.trade_sizing import can_buy_whole_share, deploy_cap_inr
from ..db.database import DB

N_ACTIONS = 3  # hold=0, buy=1, sell=2


def max_intraday_drawdown_pct() -> float:
    return float(os.getenv("MAX_INTRADAY_DRAWDOWN_PCT", "10"))


def intraday_drawdown_pct(db: DB | None, total_equity: float | None = None) -> float:
    if db is None:
        return 0.0
    from ..ops.daily_pnl import day_drawdown_pct, portfolio_state

    eq = total_equity if total_equity is not None else portfolio_state(db)["total_equity"]
    return day_drawdown_pct(db, eq)


def is_drawdown_halted(db: DB | None, total_equity: float | None = None) -> bool:
    if db is None:
        return False
    return intraday_drawdown_pct(db, total_equity) >= max_intraday_drawdown_pct()


def masked_action_probs(
    probs: np.ndarray,
    *,
    cash: float,
    ltp: float,
    db: DB | None,
    has_position: bool,
    drawdown_halted: bool = False,
) -> np.ndarray:
    """Zero invalid actions then renormalize."""
    p = np.array(probs, dtype=np.float64).copy()
    if drawdown_halted:
        p[1] = 0.0
    elif ltp > 0 and db is not None:
        cap = deploy_cap_inr(db, cash)
        if not can_buy_whole_share(ltp, cap):
            p[1] = 0.0
    elif ltp > 0 and cash < ltp:
        p[1] = 0.0
    if not has_position:
        p[2] = 0.0
    if p.sum() <= 0:
        if drawdown_halted and has_position:
            return np.array([0.0, 0.0, 1.0])
        return np.array([1.0, 0.0, 0.0])
    return p / p.sum()


def apply_action_mask(
    action: int,
    *,
    cash: float,
    ltp: float,
    db: DB | None,
    has_position: bool,
    drawdown_halted: bool = False,
) -> int:
    """Hard mask for gym env step — force hold/sell when gates trip."""
    if drawdown_halted:
        if action == 1:
            return 2 if has_position else 0
        return action
    if action == 1 and not is_buy_allowed(cash, ltp, db):
        return 0
    if action == 2 and not has_position:
        return 0
    return action


def is_buy_allowed(cash: float, ltp: float, db: DB | None) -> bool:
    if is_drawdown_halted(db):
        return False
    if ltp <= 0:
        return False
    if db is None:
        return cash >= ltp
    return can_buy_whole_share(ltp, deploy_cap_inr(db, cash)) and remaining_budget(db) >= ltp

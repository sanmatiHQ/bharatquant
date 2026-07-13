"""Trade sizing + daily budget envelope (rupees per trade, not stock price cap)."""
from __future__ import annotations

import os

from ..db.database import DB
from .budget_gate import remaining_budget


def deploy_cap_inr(db: DB, cash: float, india_vix: float = 0.0) -> float:
    """Max rupees for one new entry — driven by remaining daily budget + cash + VIX scale."""
    from .vix_controls import vix_from_db, vix_sizing_scale

    if india_vix <= 0:
        india_vix = vix_from_db(db)
    max_trade = float(os.getenv("MAX_RUPEES_PER_TRADE", "2000"))
    scale = vix_sizing_scale(india_vix)
    cap = max(0.0, min(remaining_budget(db), max_trade * scale, cash * 0.92))
    return cap


def can_buy_whole_share(ltp: float, cap_inr: float) -> bool:
    return ltp > 0 and cap_inr >= ltp

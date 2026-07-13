"""Trade sizing — budget-based, not stock price cap."""
from __future__ import annotations

import os

from src.db.database import DB, DBConfig
from src.ops.trade_sizing import can_buy_whole_share, deploy_cap_inr


def test_deploy_cap_allows_expensive_share_within_budget(tmp_path):
    os.environ["DAILY_INVESTMENT_MAX"] = "2000"
    os.environ["MAX_RUPEES_PER_TRADE"] = "2000"
    os.environ["BUDGET_ROLLOVER_MODE"] = "strict"
    db = DB(DBConfig(sqlite_path=str(tmp_path / "s.db")))
    db.add_cash(1, 10000, "seed")
    cap = deploy_cap_inr(db, 10000)
    assert cap == 2000
    assert can_buy_whole_share(2199, cap) is False
    assert can_buy_whole_share(1999, cap) is True

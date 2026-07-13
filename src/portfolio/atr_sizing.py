"""ATR-based position sizing helper."""
from __future__ import annotations

import os

import pandas as pd

from ..db.database import DB
from ..features.indicators import atr
from ..ops.budget_gate import remaining_budget


def atr_qty_for_symbol(db: DB, symbol: str, ltp: float, cash: float, max_trade: float) -> int:
    """
    Volatility-targeted sizing: smaller qty when ATR% is high.
    Falls back to budget-only sizing when no bar history.
    """
    if ltp <= 0:
        return 0
    sym = symbol.replace("NSE:", "")
    rows = db._conn.execute(
        """
        SELECT high, low, close FROM bar_log
        WHERE symbol=? AND interval='5m'
        ORDER BY ts DESC LIMIT 30
        """,
        (sym,),
    ).fetchall()
    cap = min(max_trade, remaining_budget(db), cash * 0.92)
    if len(rows) < 14:
        return max(0, int(cap // ltp)) if cap >= ltp else 0

    df = pd.DataFrame([dict(r) for r in reversed(rows)])
    atr14 = float(atr(df["high"], df["low"], df["close"]).iloc[-1])
    atr_pct = (atr14 / ltp * 100.0) if ltp > 0 else 2.0
    target_risk_pct = float(os.getenv("ATR_TARGET_RISK_PCT", "1.0"))
    # Higher ATR → deploy less notional
    vol_scalar = max(0.35, min(1.0, target_risk_pct / max(0.5, atr_pct)))
    adjusted_cap = cap * vol_scalar
    if adjusted_cap < ltp:
        return 0
    return max(1, int(adjusted_cap // ltp))

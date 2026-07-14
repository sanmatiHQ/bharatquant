"""Portfolio beta-weighted exposure vs Nifty — caps correlated directional risk."""
from __future__ import annotations

import os

from ..db.database import DB

_BETA_WINDOW = int(os.getenv("BETA_LOOKBACK_BARS", "20"))


def _index_returns(db: DB) -> list[float]:
    rows = db._conn.execute(
        """
        SELECT close FROM bar_log
        WHERE symbol IN ('NIFTY50','NIFTYBEES') AND interval='5m'
        ORDER BY ts DESC LIMIT ?
        """,
        (_BETA_WINDOW + 1,),
    ).fetchall()
    if len(rows) < 6:
        return []
    closes = [float(r["close"]) for r in reversed(rows)]
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]


def symbol_beta_to_index(db: DB, symbol: str) -> float:
    sym = symbol.replace("NSE:", "")
    idx_rets = _index_returns(db)
    if len(idx_rets) < 5:
        return 1.0
    rows = db._conn.execute(
        """
        SELECT close FROM bar_log
        WHERE symbol=? AND interval='5m'
        ORDER BY ts DESC LIMIT ?
        """,
        (sym, _BETA_WINDOW + 1),
    ).fetchall()
    if len(rows) < 6:
        return 1.0
    closes = [float(r["close"]) for r in reversed(rows)]
    sym_rets = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    n = min(len(sym_rets), len(idx_rets))
    if n < 5:
        return 1.0
    sr = sym_rets[-n:]
    ir = idx_rets[-n:]
    mean_s = sum(sr) / n
    mean_i = sum(ir) / n
    cov = sum((sr[j] - mean_s) * (ir[j] - mean_i) for j in range(n)) / n
    var_i = sum((ir[j] - mean_i) ** 2 for j in range(n)) / n
    if var_i <= 1e-12:
        return 1.0
    beta = cov / var_i
    return max(-2.0, min(2.5, beta))


def portfolio_beta_exposure_inr(db: DB) -> float:
    exp = 0.0
    for r in db._conn.execute("SELECT symbol, qty, last_price FROM positions WHERE qty > 0"):
        val = float(r["qty"]) * float(r["last_price"])
        exp += abs(symbol_beta_to_index(db, str(r["symbol"]))) * val
    return exp


def can_add_beta_exposure(db: DB, symbol: str, rupees: float, equity: float) -> tuple[bool, str]:
    max_mult = float(os.getenv("MAX_PORTFOLIO_BETA_MULT", "1.35"))
    if equity <= 0:
        return True, "ok"
    beta = abs(symbol_beta_to_index(db, symbol))
    current = portfolio_beta_exposure_inr(db)
    projected = current + beta * rupees
    if projected / equity > max_mult:
        return False, f"portfolio_beta_cap_{projected/equity:.2f}"
    return True, "ok"

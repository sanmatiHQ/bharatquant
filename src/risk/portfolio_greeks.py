"""Portfolio Greeks aggregation and caps — defined-risk enforcement for OPT rail."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ..db.database import DB


@dataclass
class PortfolioGreeks:
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    net_short_premium: float = 0.0


def _cap(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def aggregate_portfolio_greeks(db: DB) -> PortfolioGreeks:
    rows = db._conn.execute(
        """
        SELECT symbol, qty, avg_price, rail FROM positions WHERE qty > 0
        """
    ).fetchall()
    g = PortfolioGreeks()
    for r in rows:
        rail = str(r["rail"] or "CNC").upper()
        qty = int(r["qty"])
        sym = str(r["symbol"])
        if rail != "OPT":
            g.delta += qty * float(r["avg_price"])
            continue
        row = db._conn.execute(
            """
            SELECT iv, ltp, option_type FROM option_iv
            WHERE symbol=? ORDER BY ts DESC LIMIT 1
            """,
            (sym.split(":")[0] if ":" in sym else sym,),
        ).fetchone()
        if not row:
            continue
        iv = float(row["iv"] or 15)
        ltp = float(row["ltp"] or 0)
        sign = 1.0 if qty > 0 else -1.0
        opt_type = str(row.get("option_type") or "CE").upper()
        delta_proxy = sign * (0.55 if opt_type == "CE" else -0.45)
        g.delta += delta_proxy * abs(qty) * ltp
        g.gamma += abs(qty) * ltp * 0.002
        g.vega += abs(qty) * ltp * (iv / 100.0) * 0.12
        g.theta += -abs(qty) * ltp * 0.015
    return g


def greeks_within_caps(db: DB, *, add_delta: float = 0.0, add_vega: float = 0.0, naked_short: bool = False) -> tuple[bool, str]:
    g = aggregate_portfolio_greeks(db)
    max_delta = _cap("PORTFOLIO_MAX_DELTA", 50000)
    max_vega = _cap("PORTFOLIO_MAX_VEGA", 8000)
    max_gamma = _cap("PORTFOLIO_MAX_GAMMA", 2000)
    if abs(g.delta + add_delta) > max_delta:
        return False, f"portfolio_delta_cap_{g.delta + add_delta:.0f}"
    if abs(g.vega + add_vega) > max_vega:
        return False, f"portfolio_vega_cap_{g.vega + add_vega:.0f}"
    if abs(g.gamma) > max_gamma:
        return False, f"portfolio_gamma_cap_{g.gamma:.0f}"
    if naked_short and os.getenv("FO_DEFINED_RISK_ONLY", "true").lower() in ("1", "true", "yes"):
        return False, "naked_option_short_blocked"
    return True, "ok"


def stress_book_loss_inr(db: DB, equity: float) -> dict[str, Any]:
    """Stress: Nifty -5% spot + VIX doubles (approx vega shock)."""
    g = aggregate_portfolio_greeks(db)
    spot_shock = -0.05 * equity * 0.6
    vix_shock = g.vega * 0.5
    gamma_shock = 0.5 * g.gamma * (0.05 ** 2) * 1e4
    total = spot_shock + vix_shock + gamma_shock
    limit_pct = float(os.getenv("FO_STRESS_LOSS_LIMIT_PCT", "4"))
    limit_inr = equity * limit_pct / 100.0
    return {
        "stress_loss_inr": round(total, 2),
        "limit_inr": round(limit_inr, 2),
        "pass": abs(total) <= limit_inr,
        "delta": g.delta,
        "vega": g.vega,
        "gamma": g.gamma,
    }

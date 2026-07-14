"""Event-driven regime switching — vol shock + persistence dampener."""
from __future__ import annotations

import math
import os

from ..db.database import DB


def _trailing_index_vol(db: DB, *, days: int = 20) -> float:
    """20-day trailing realized vol from NIFTY 5m closes (annualized proxy)."""
    rows = db._conn.execute(
        """
        SELECT close FROM bar_log
        WHERE symbol IN ('NIFTY50','NIFTYBEES') AND interval='5m'
        ORDER BY ts DESC LIMIT ?
        """,
        (days * 78 + 2,),
    ).fetchall()
    if len(rows) < 30:
        return 0.15
    closes = [float(r["close"]) for r in reversed(rows)]
    rets = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    if len(rets) < 10:
        return 0.15
    vol = math.sqrt(sum(r * r for r in rets) / len(rets))
    return max(0.05, vol * math.sqrt(252 * 78))


def realized_vol_15m(ctx) -> float:
    """Last 15 minutes = 3×5m index returns on ctx."""
    rets = list(getattr(ctx, "index_returns", []) or [])[-3:]
    if len(rets) < 2:
        return 0.0
    return math.sqrt(sum(r * r for r in rets) / len(rets))


def return_15m(ctx) -> float:
    rets = list(getattr(ctx, "index_returns", []) or [])[-3:]
    return sum(rets) if rets else 0.0


def check_regime_shock(db: DB, ctx) -> bool:
    """
    True when intraday vol or return exceeds trailing norms — force regime recompute.
    Vol spike: 15m realized vol > 2σ above trailing 20d average.
    Return shock: |15m return| > threshold (default 0.35%).
    """
    trail = _trailing_index_vol(db)
    rv15 = realized_vol_15m(ctx)
    ret15 = return_15m(ctx)
    vol_mult = float(os.getenv("REGIME_VOL_SPIKE_MULT", "2.0"))
    ret_thresh = float(os.getenv("REGIME_RETURN_SHOCK_PCT", "0.0035"))
    vol_shock = rv15 > trail * vol_mult / math.sqrt(252 * 78) if trail > 0 else False
    ret_shock = abs(ret15) >= ret_thresh
    return vol_shock or ret_shock


def apply_regime_persistence(ctx, raw_regime: str, *, shock: bool = False) -> str:
    """
    Require N consecutive bars of same raw regime before whitelist switches.
    On shock, require only 1 bar (fast react, still avoids single-tick flicker).
    """
    persist = 1 if shock else int(os.getenv("REGIME_PERSIST_BARS", "3"))
    pending = getattr(ctx, "_regime_pending", None)
    count = int(getattr(ctx, "_regime_pending_count", 0) or 0)
    effective = str(getattr(ctx, "regime", raw_regime) or raw_regime)
    if effective in ("NEUTRAL", ""):
        ctx.regime = raw_regime
        ctx.regime_raw = raw_regime  # type: ignore[attr-defined]
        return raw_regime

    if raw_regime == effective:
        ctx._regime_pending = None  # type: ignore[attr-defined]
        ctx._regime_pending_count = 0  # type: ignore[attr-defined]
        ctx.regime_raw = raw_regime  # type: ignore[attr-defined]
        return effective

    if pending == raw_regime:
        count += 1
    else:
        pending = raw_regime
        count = 1

    ctx._regime_pending = pending  # type: ignore[attr-defined]
    ctx._regime_pending_count = count  # type: ignore[attr-defined]
    ctx.regime_raw = raw_regime  # type: ignore[attr-defined]

    if count >= persist:
        ctx.regime = raw_regime
        ctx._regime_pending = None  # type: ignore[attr-defined]
        ctx._regime_pending_count = 0  # type: ignore[attr-defined]
        return raw_regime
    return effective

"""Historical walk-forward pre-screen — candidacy priority only, not promotion."""
from __future__ import annotations

from typing import Any, Optional

from ..db.database import DB


def get_historical_screen(db: DB, strategy_id: str) -> Optional[dict[str, Any]]:
    row = db._conn.execute(
        """
        SELECT strategy_id, screened_ts, interval, sample_count, win_rate,
               sortino, calmar, max_drawdown_pct, binomial_p, composite,
               cleared, status, lookback_days
        FROM historical_screen WHERE strategy_id=?
        """,
        (strategy_id,),
    ).fetchone()
    return dict(row) if row else None


def candidacy_priority_multiplier(db: DB, strategy_id: str) -> float:
    """Boost signal priority for strategies that cleared historical pre-screen."""
    return screen_priority_multiplier(db, strategy_id)


def screen_priority_multiplier(db: DB, strategy_id: str) -> float:
    """
    Boost paper signal generation for cleared historical screen (any lifecycle state).
    Does not change lifecycle or capital gate thresholds.
    """
    row = get_historical_screen(db, strategy_id)
    if not row or not int(row.get("cleared") or 0):
        return 1.0
    comp = float(row.get("composite") or 0)
    return min(1.8, 1.15 + comp * 0.15)


def list_historical_screen(db: DB, *, cleared_only: bool = False) -> list[dict[str, Any]]:
    q = """
        SELECT strategy_id, screened_ts, interval, sample_count, win_rate,
               sortino, calmar, max_drawdown_pct, binomial_p, composite,
               cleared, status, lookback_days
        FROM historical_screen
    """
    if cleared_only:
        q += " WHERE cleared=1"
    q += " ORDER BY composite DESC, sample_count DESC"
    return [dict(r) for r in db._conn.execute(q).fetchall()]

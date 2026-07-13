"""Micro sparkline series from tick_log for dashboard rows."""
from __future__ import annotations

from ..db.database import DB


def sparklines_for_symbols(db: DB, symbols: list[str], points: int = 24) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for sym in symbols[:20]:
        sym = sym.replace("NSE:", "")
        rows = db._conn.execute(
            """
            SELECT ltp FROM tick_log WHERE symbol=? ORDER BY ts DESC LIMIT ?
            """,
            (sym, points),
        ).fetchall()
        if rows:
            out[sym] = [float(r["ltp"]) for r in reversed(rows)]
    return out

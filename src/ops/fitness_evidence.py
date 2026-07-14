"""After-cost fitness evidence from closed trades and portfolio history — capital gate inputs."""
from __future__ import annotations

import os
import time
from typing import Any

from ..db.database import DB
from ..risk.risk_metrics import PERIODS_PER_YEAR_SIGNAL, fitness_from_returns, max_drawdown_from_returns

CLOCK_START_KEY = "capital_clock_start_ts"


def ensure_capital_clock(db: DB, *, start_ts: int | None = None) -> int:
    """Start or reset the go-live measurement clock."""
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (CLOCK_START_KEY,)).fetchone()
    if row and str(row["v"]).isdigit():
        return int(row["v"])
    ts = start_ts or int(time.time())
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (CLOCK_START_KEY, str(ts)),
        )
    return ts


def reset_capital_clock(db: DB, reason: str) -> int:
    ts = int(time.time())
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (CLOCK_START_KEY, str(ts)),
        )
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("capital_clock_reset_reason", reason[:500]),
        )
    return ts


def clock_start_ts(db: DB) -> int:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (CLOCK_START_KEY,)).fetchone()
    if row and str(row["v"]).isdigit():
        return int(row["v"])
    return ensure_capital_clock(db)


def closed_sell_returns(db: DB, since_ts: int) -> list[float]:
    """Fractional return per closed SELL (after fees), using FIFO cost basis reconstruction."""
    rows = db._conn.execute(
        """
        SELECT ts, symbol, qty, price, amount, fees
        FROM trades
        WHERE side='SELL' AND ts >= ?
        ORDER BY ts ASC
        """,
        (since_ts,),
    ).fetchall()
    returns: list[float] = []
    for r in rows:
        qty = int(r["qty"] or 0)
        if qty <= 0:
            continue
        sell_px = float(r["price"] or 0)
        fees = float(r["fees"] or 0)
        proceeds = float(r["amount"] or 0)
        sym = str(r["symbol"])
        ts = int(r["ts"])
        buy_row = db._conn.execute(
            """
            SELECT SUM(remaining_qty * buy_price) / NULLIF(SUM(remaining_qty), 0) AS avg_buy
            FROM fifo_lots
            WHERE symbol=? AND buy_ts <= ?
            """,
            (sym, ts),
        ).fetchone()
        avg_buy = float(buy_row["avg_buy"] or 0) if buy_row and buy_row["avg_buy"] else sell_px
        cost_basis = avg_buy * qty
        if cost_basis <= 0:
            cost_basis = max(proceeds, sell_px * qty)
        net = proceeds - fees if proceeds > 0 else sell_px * qty - fees
        ret = (net - cost_basis) / cost_basis
        returns.append(ret)
    return returns


def portfolio_period_returns(db: DB, since_ts: int) -> list[float]:
    rows = db._conn.execute(
        """
        SELECT total_value FROM portfolio_history
        WHERE ts >= ? AND total_value > 0
        ORDER BY ts ASC
        """,
        (since_ts,),
    ).fetchall()
    values = [float(r["total_value"]) for r in rows]
    out: list[float] = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev > 0:
            out.append((values[i] - prev) / prev)
    return out


def closed_trade_count(db: DB, since_ts: int) -> int:
    row = db._conn.execute(
        "SELECT COUNT(*) AS n FROM trades WHERE side='SELL' AND ts >= ?",
        (since_ts,),
    ).fetchone()
    return int(row["n"] or 0)


def trading_weeks_with_activity(db: DB, since_ts: int) -> int:
    rows = db._conn.execute(
        """
        SELECT DISTINCT strftime('%Y-%W', datetime(ts, 'unixepoch', '+5 hours')) AS w
        FROM trades
        WHERE ts >= ?
        """,
        (since_ts,),
    ).fetchall()
    return len(rows)


def promoted_full_count(db: DB) -> int:
    """Strategies at `full` that passed discovery/lifecycle — excludes default core registry."""
    row = db._conn.execute(
        """
        SELECT COUNT(*) AS n FROM strategy_lifecycle
        WHERE state='full' AND strategy_id LIKE 'learned_%'
        """,
    ).fetchone()
    return int(row["n"] or 0)


def max_observed_drawdown_pct(db: DB, since_ts: int) -> float:
    rows = db._conn.execute(
        """
        SELECT total_value FROM portfolio_history
        WHERE ts >= ? AND total_value > 0
        ORDER BY ts ASC
        """,
        (since_ts,),
    ).fetchall()
    values = [float(r["total_value"]) for r in rows]
    if len(values) < 2:
        sells = closed_sell_returns(db, since_ts)
        if len(sells) >= 5:
            return max_drawdown_from_returns(sells) * 100.0
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    return max_dd * 100.0


def system_fitness_snapshot(db: DB, since_ts: int | None = None) -> dict[str, Any]:
    start = since_ts or clock_start_ts(db)
    sell_rets = closed_sell_returns(db, start)
    port_rets = portfolio_period_returns(db, start)
    series = sell_rets if len(sell_rets) >= 10 else port_rets
    fit = fitness_from_returns(series, periods_per_year=PERIODS_PER_YEAR_SIGNAL) if series else fitness_from_returns([], periods_per_year=PERIODS_PER_YEAR_SIGNAL)
    return {
        "clock_start_ts": start,
        "closed_sells": len(sell_rets),
        "portfolio_points": len(port_rets),
        "sample_n": fit.n,
        "sortino": round(fit.sortino, 4),
        "calmar": round(fit.calmar, 4),
        "composite": round(fit.composite, 4),
        "max_drawdown_pct": round(max_observed_drawdown_pct(db, start), 2),
        "trading_weeks": trading_weeks_with_activity(db, start),
        "promoted_full_learned": promoted_full_count(db),
        "series_source": "closed_sells" if len(sell_rets) >= 10 else "portfolio_history",
    }

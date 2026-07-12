"""Daily P&L tracking for rupee loss halt — BQ-A6."""
from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from ..ops.kill_switch import get_setting, set_setting

_TZ = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))


def _today_key() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def ensure_day_baseline(db, total_equity: float) -> None:
    """Record start-of-day equity once per IST calendar day."""
    key = f"day_start_{_today_key()}"
    if get_setting(db, key) is None:
        set_setting(db, key, f"{total_equity:.4f}")
        set_setting(db, f"day_peak_{_today_key()}", f"{total_equity:.4f}")


def update_day_peak(db, total_equity: float) -> None:
    peak_key = f"day_peak_{_today_key()}"
    cur = get_setting(db, peak_key)
    peak = float(cur) if cur else total_equity
    if total_equity > peak:
        set_setting(db, peak_key, f"{total_equity:.4f}")


def day_loss_rupees(db, total_equity: float) -> float:
    key = f"day_start_{_today_key()}"
    start_s = get_setting(db, key)
    if not start_s:
        return 0.0
    return max(0.0, float(start_s) - total_equity)


def day_drawdown_pct(db, total_equity: float) -> float:
    peak_key = f"day_peak_{_today_key()}"
    peak_s = get_setting(db, peak_key)
    if not peak_s:
        return 0.0
    peak = float(peak_s)
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - total_equity) / peak * 100.0)


def portfolio_state(db) -> dict:
    conn = db._conn
    cash = float(conn.execute("SELECT IFNULL(SUM(delta),0) c FROM cash_ledger").fetchone()["c"])
    hv = float(conn.execute("SELECT IFNULL(SUM(qty*last_price),0) h FROM positions").fetchone()["h"])
    n = int(conn.execute("SELECT COUNT(*) n FROM positions").fetchone()["n"])
    total = cash + hv
    ensure_day_baseline(db, total)
    update_day_peak(db, total)
    peak_key = f"day_peak_{_today_key()}"
    peak_s = get_setting(db, peak_key)
    return {
        "total_equity": total,
        "day_peak_equity": float(peak_s) if peak_s else total,
        "day_loss_rupees": day_loss_rupees(db, total),
        "open_positions": n,
        "cash": cash,
        "holdings_value": hv,
    }


def snapshot_portfolio_close(db) -> None:
    """Persist end-of-day portfolio row."""
    st = portfolio_state(db)
    conn = db._conn
    buy = float(conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY'").fetchone()[0])
    sell = float(conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='SELL'").fetchone()[0])
    realized = sell - buy
    unrealized = float(
        conn.execute("SELECT IFNULL(SUM((last_price-avg_price)*qty),0) FROM positions").fetchone()[0]
    )
    hist = conn.execute("SELECT total_value FROM portfolio_history ORDER BY ts DESC LIMIT 1").fetchone()
    peak = float(hist["total_value"]) if hist else st["total_equity"]
    max_dd = 0.0
    if peak > 0:
        max_dd = max(0.0, (peak - st["total_equity"]) / peak * 100.0)
    db.snapshot_portfolio(
        int(time.time()),
        st["cash"],
        st["holdings_value"],
        st["total_equity"],
        realized,
        unrealized,
        max_dd,
    )

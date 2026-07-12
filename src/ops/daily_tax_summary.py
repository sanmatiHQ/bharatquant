"""End-of-day after-cost, after-tax P&L summary."""
from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db.database import DB

_TZ = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
STCG_RATE = float(os.getenv("STCG_TAX_RATE", "0.125"))
LTCG_RATE = float(os.getenv("LTCG_TAX_RATE", "0.125"))


def _today_start_ts() -> int:
    now = datetime.now(_TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def build_daily_summary(db: DB) -> dict:
    ts0 = _today_start_ts()
    conn = db._conn
    sells = conn.execute(
        """
        SELECT side, amount, fees, stcg_ltcg FROM trades
        WHERE ts >= ? AND side = 'SELL'
        """,
        (ts0,),
    ).fetchall()
    buys = conn.execute(
        "SELECT IFNULL(SUM(amount),0) FROM trades WHERE ts >= ? AND side='BUY'",
        (ts0,),
    ).fetchone()[0]
    gross_realized = 0.0
    total_fees = 0.0
    stcg_pnl = 0.0
    ltcg_pnl = 0.0
    for r in sells:
        amt = float(r["amount"])
        fees = float(r["fees"] or 0)
        total_fees += fees
        gross_realized += amt
        tax_cls = str(r["stcg_ltcg"] or "NA")
        if tax_cls == "STCG":
            stcg_pnl += amt
        elif tax_cls == "LTCG":
            ltcg_pnl += amt
    net_before_tax = gross_realized - float(buys or 0)
    est_stcg_tax = max(0.0, stcg_pnl * STCG_RATE)
    est_ltcg_tax = max(0.0, ltcg_pnl * LTCG_RATE)
    net_after_tax = net_before_tax - est_stcg_tax - est_ltcg_tax - total_fees
    cash = float(conn.execute("SELECT IFNULL(SUM(delta),0) FROM cash_ledger").fetchone()[0])
    holdings = float(conn.execute("SELECT IFNULL(SUM(qty*last_price),0) FROM positions").fetchone()[0])
    summary = {
        "date": datetime.now(_TZ).date().isoformat(),
        "gross_sell_inr": gross_realized,
        "gross_buy_inr": float(buys or 0),
        "total_fees_inr": total_fees,
        "net_before_tax_inr": net_before_tax,
        "est_stcg_tax_inr": est_stcg_tax,
        "est_ltcg_tax_inr": est_ltcg_tax,
        "net_after_tax_inr": net_after_tax,
        "cash_inr": cash,
        "holdings_inr": holdings,
        "total_equity_inr": cash + holdings,
        "trade_count": conn.execute("SELECT COUNT(*) FROM trades WHERE ts >= ?", (ts0,)).fetchone()[0],
    }
    return summary


def persist_daily_summary(db: DB) -> dict:
    summary = build_daily_summary(db)
    ts = int(time.time())
    with db.tx() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO daily_tax_summary(
              summary_date, ts, gross_buy, gross_sell, total_fees,
              net_before_tax, est_stcg_tax, est_ltcg_tax, net_after_tax, total_equity, trade_count
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                summary["date"],
                ts,
                summary["gross_buy_inr"],
                summary["gross_sell_inr"],
                summary["total_fees_inr"],
                summary["net_before_tax_inr"],
                summary["est_stcg_tax_inr"],
                summary["est_ltcg_tax_inr"],
                summary["net_after_tax_inr"],
                summary["total_equity_inr"],
                summary["trade_count"],
            ),
        )
    return summary

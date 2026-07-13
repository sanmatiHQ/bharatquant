"""Today's trades, PnL ledger, and tomorrow plan — always-on dashboard truth."""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import os

from ..db.database import DB


def _today_start_ts() -> int:
    tz = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
    now = datetime.now(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


def _setting(db: DB, key: str) -> dict | None:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["v"])
    except json.JSONDecodeError:
        return {"text": str(row["v"])}


def synthesize_tomorrow_plan(db: DB, *, pnl: dict, budget: dict) -> str:
    """Fallback plan when 08:45 premarket routine has not run yet."""
    watch = [
        dict(r)
        for r in db._conn.execute(
            """
            SELECT symbol, momentum_score FROM screening_results
            WHERE run_ts = (SELECT MAX(run_ts) FROM screening_results)
            ORDER BY momentum_score DESC LIMIT 5
            """
        ).fetchall()
    ]
    top = ", ".join(w["symbol"] for w in watch[:5]) or "run screening first"
    deployed = float(budget.get("deployed_today_inr", 0) or 0)
    cap = float(budget.get("daily_max_inr", 0) or 0)
    total = float(pnl.get("total_pnl", 0) or 0)
    return (
        f"Auto plan (pre-08:45): Tomorrow deploy up to ₹{cap:,.0f} "
        f"(used ₹{deployed:,.0f} today). "
        f"Today PnL ₹{total:+,.0f}. "
        f"Priority watchlist: {top}. "
        f"Full LLM bias + regime swap fires at 08:45 IST pre-market."
    )


def build_session_ledger(db: DB) -> dict[str, Any]:
    """Single object for dashboard: what we traded, PnL, plan for tomorrow."""
    today = _today_start_ts()
    conn = db._conn

    trades = [
        dict(r)
        for r in conn.execute(
            """
            SELECT ts, symbol, side, qty, price, amount, reason
            FROM trades WHERE ts >= ? ORDER BY ts DESC LIMIT 30
            """,
            (today,),
        ).fetchall()
    ]
    if not trades:
        trades = [
            dict(r)
            for r in conn.execute(
                """
                SELECT ts, symbol, side, qty, price, amount, reason
                FROM trades ORDER BY ts DESC LIMIT 15
                """
            ).fetchall()
        ]

    buy = float(conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY'").fetchone()[0])
    sell = float(conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='SELL'").fetchone()[0])
    unreal = float(
        conn.execute("SELECT IFNULL(SUM((last_price-avg_price)*qty),0) FROM positions").fetchone()[0]
    )
    realized = sell - buy
    total_pnl = realized + unreal

    from ..ops.budget_gate import budget_status

    budget = budget_status(db)

    premarket = _setting(db, "premarket_brief_latest")
    postmortem = _setting(db, "llm_postmortem_latest")
    eod = _setting(db, "eod_scan_latest")

    plan_parts: list[str] = []
    if premarket and premarket.get("text"):
        plan_parts.append(premarket["text"])
    elif postmortem and postmortem.get("summary"):
        plan_parts.append(f"Post-session: {postmortem['summary']}")
    else:
        plan_parts.append(
            synthesize_tomorrow_plan(
                db,
                pnl={"total_pnl": total_pnl},
                budget=budget,
            )
        )

    if postmortem and postmortem.get("summary") and premarket:
        plan_parts.append(f"Yesterday review: {postmortem['summary']}")
    if eod and eod.get("summary"):
        plan_parts.append(f"EOD scan: {eod['summary']}")

    trade_lines = []
    for t in trades[:12]:
        trade_lines.append(
            {
                "ts": t["ts"],
                "text": f"{t['side']} {t['qty']} {t['symbol']} @ ₹{float(t['price']):.2f}",
                "amount": float(t["amount"] or 0),
                "reason": t.get("reason") or "",
            }
        )

    return {
        "ts": int(time.time()),
        "pnl": {
            "total": round(total_pnl, 2),
            "realized": round(realized, 2),
            "unrealized": round(unreal, 2),
            "buy_notional": round(buy, 2),
            "sell_notional": round(sell, 2),
        },
        "trade_count": len(trades),
        "trades": trade_lines,
        "plan_for_tomorrow": " ".join(plan_parts),
        "premarket_ts": premarket.get("ts") if premarket else None,
        "has_official_premarket": bool(premarket and premarket.get("text")),
        "budget": {
            "deployed_today": budget.get("deployed_today_inr"),
            "daily_max": budget.get("daily_max_inr"),
            "remaining": budget.get("remaining_inr"),
        },
    }

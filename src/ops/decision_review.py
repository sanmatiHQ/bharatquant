"""Agent learning review — decision impact, missed trades, improvement hints."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .budget_gate import budget_status, deployed_today_inr
from ..db.database import DB

IST = timezone(timedelta(hours=5, minutes=30))


def _today_start_ts() -> int:
    now = datetime.now(IST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def build_learning_review(db: DB) -> dict[str, Any]:
    today = _today_start_ts()
    conn = db._conn

    deployed = deployed_today_inr(db)
    sold = float(
        conn.execute(
            "SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='SELL' AND ts >= ?",
            (today,),
        ).fetchone()[0]
    )
    trade_count = int(
        conn.execute("SELECT COUNT(*) FROM trades WHERE ts >= ?", (today,)).fetchone()[0]
    )
    realized_today = sold - deployed

    unrealized = float(
        conn.execute(
            "SELECT IFNULL(SUM((last_price-avg_price)*qty),0) FROM positions WHERE qty>0"
        ).fetchone()[0]
    )
    cash = float(conn.execute("SELECT IFNULL(SUM(delta),0) FROM cash_ledger").fetchone()[0])

    budget_min = float(os.getenv("DAILY_INVESTMENT_MIN", "1000"))
    budget_max = float(os.getenv("DAILY_INVESTMENT_MAX", "2000"))
    bstat = budget_status(db)
    budget_max = float(bstat["daily_max_inr"])

    signals_today = int(
        conn.execute("SELECT COUNT(*) FROM strategy_ledger WHERE ts >= ?", (today,)).fetchone()[0]
    )
    executed_today = int(
        conn.execute(
            "SELECT COUNT(*) FROM strategy_ledger WHERE ts >= ? AND executed=1",
            (today,),
        ).fetchone()[0]
    )
    vetoed_today = signals_today - executed_today

    missed = [
        dict(r)
        for r in conn.execute(
            """
            SELECT strategy_id, symbol, signal, confidence, reason, ts
            FROM strategy_ledger
            WHERE ts >= ? AND executed=0 AND confidence >= 0.6
            ORDER BY confidence DESC LIMIT 15
            """,
            (today,),
        ).fetchall()
    ]

    shadows = [
        dict(r)
        for r in conn.execute(
            "SELECT strategy_id, symbol, action, confidence, reason, ts FROM shadow_trades WHERE ts >= ? ORDER BY ts DESC LIMIT 10",
            (today,),
        ).fetchall()
    ]

    strategy_pnl = [
        dict(r)
        for r in conn.execute(
            "SELECT strategy_id, realized_pnl, trade_count FROM strategy_pnl ORDER BY realized_pnl DESC"
        ).fetchall()
    ]

    rl_row = conn.execute(
        "SELECT COUNT(*) c, AVG(reward) avg_r, SUM(CASE WHEN reward>0 THEN 1 ELSE 0 END) wins FROM rl_transitions WHERE ts >= ?",
        (today,),
    ).fetchone()
    rl_total = int(conn.execute("SELECT COUNT(*) FROM rl_transitions").fetchone()[0])

    dec_raw = conn.execute("SELECT v FROM settings WHERE k='agent_last_decision'").fetchone()
    last_decision = None
    if dec_raw:
        try:
            last_decision = json.loads(dec_raw["v"])
        except json.JSONDecodeError:
            pass

    veto_reasons: dict[str, int] = {}
    for row in conn.execute(
        """
        SELECT reason, COUNT(*) c FROM strategy_ledger
        WHERE ts >= ? AND executed=0 AND reason IS NOT NULL
        GROUP BY reason ORDER BY c DESC LIMIT 8
        """,
        (today,),
    ).fetchall():
        veto_reasons[str(row["reason"])] = int(row["c"])

    improvements = _recommendations(
        deployed=deployed,
        budget_min=budget_min,
        budget_max=budget_max,
        vetoed_today=vetoed_today,
        executed_today=executed_today,
        realized_today=realized_today,
        unrealized=unrealized,
        rl_total=rl_total,
        strategy_pnl=strategy_pnl,
    )

    universe_tier = os.getenv("UNIVERSE_TIER", "main")
    options_paper = os.getenv("OPTIONS_PAPER_ENABLED", "true").lower() in ("1", "true", "yes")

    feed_health = _feed_health(conn)

    return {
        "date_ist": datetime.now(IST).strftime("%Y-%m-%d"),
        "daily_budget_inr": {"min": budget_min, "max": budget_max},
        "deployed_today_inr": round(deployed, 2),
        "budget_used_pct": round(deployed / budget_max * 100, 1) if budget_max else 0,
        "realized_pnl_today_inr": round(realized_today, 2),
        "unrealized_pnl_inr": round(unrealized, 2),
        "cash_inr": round(cash, 2),
        "trades_today": trade_count,
        "signals_today": signals_today,
        "executed_signals_today": executed_today,
        "vetoed_signals_today": vetoed_today,
        "veto_reasons": veto_reasons,
        "missed_high_confidence": missed,
        "shadow_trades": shadows,
        "strategy_pnl": strategy_pnl,
        "rl_transitions_today": int(rl_row["c"]) if rl_row else 0,
        "rl_avg_reward_today": round(float(rl_row["avg_r"] or 0), 4) if rl_row else 0,
        "rl_total_transitions": rl_total,
        "last_decision": last_decision,
        "improvements": improvements,
        "universe_tier": universe_tier,
        "options_paper_enabled": options_paper,
        "feed_health": feed_health,
        "budget_pending": bstat.get("pending_increase"),
        "budget_remaining_inr": bstat.get("remaining_inr"),
        "ts": int(time.time()),
    }


def _feed_health(conn) -> dict[str, Any]:
    """Recent ingest_log freshness for cross-market feeds."""
    now = int(time.time())
    out: dict[str, Any] = {}
    for event_type, key in (
        ("GIFT_TICK", "gift_nifty"),
        ("FII_DII_UPDATE", "fii_dii"),
        ("GIFT_SESSION_CHANGE", "global_macro"),
        ("INSIDER_FILING", "insider"),
        ("BLOCK_DEAL", "bulk_deals"),
        ("NEWS_ALERT", "corp_announce"),
    ):
        row = conn.execute(
            "SELECT ts, source FROM ingest_log WHERE event_type=? ORDER BY ts DESC LIMIT 1",
            (event_type,),
        ).fetchone()
        if row:
            age = now - int(row["ts"])
            out[key] = {"ok": age < 900, "age_sec": age, "source": row["source"]}
        else:
            out[key] = {"ok": False, "age_sec": None, "source": None}
    return out


def _recommendations(
    *,
    deployed: float,
    budget_min: float,
    budget_max: float,
    vetoed_today: int,
    executed_today: int,
    realized_today: float,
    unrealized: float,
    rl_total: int,
    strategy_pnl: list[dict],
) -> list[str]:
    tips: list[str] = []
    if deployed < budget_min:
        tips.append(
            f"Deployed only ₹{deployed:.0f} today — target ₹{budget_min:.0f}–₹{budget_max:.0f}. "
            "Check affordability vetoes on high-priced stocks or widen universe to mid/small caps."
        )
    if vetoed_today > executed_today * 3 and vetoed_today > 10:
        tips.append(
            f"{vetoed_today} signals vetoed vs {executed_today} executed — review regime whitelist, "
            "cost-edge gate, and cash vs LTP (whole shares only in India)."
        )
    if realized_today < 0 and unrealized < 0:
        tips.append("Both realized and unrealized PnL negative — tighten stops or reduce MIS size until RL has more data.")
    elif unrealized > 0 and realized_today <= 0:
        tips.append("Open positions in profit but no exits yet — trailing stop / take-profit should harvest gains.")
    if rl_total < 50:
        tips.append(
            f"RL has {rl_total} transitions — needs ~80+ before policy can veto bad trades. Keep paper trading to learn."
        )
    if not strategy_pnl:
        tips.append("No closed strategy PnL yet — bandit weights are uniform. Exits will unlock per-strategy learning.")
    losing = [s for s in strategy_pnl if float(s.get("realized_pnl", 0)) < 0]
    if losing:
        tips.append(
            "Underperforming strategies: "
            + ", ".join(f"{s['strategy_id']} (₹{s['realized_pnl']:.0f})" for s in losing[:3])
            + " — bandit will down-weight these hourly."
        )
    tier = os.getenv("UNIVERSE_TIER", "main")
    if tier == "main":
        tips.append(
            "Universe is main-board only (~2,335 stocks). Set UNIVERSE_TIER=with_sme to include SME small caps."
        )
    if not tips:
        tips.append("On track — agent is deploying capital, logging decisions, and building RL transitions.")
    return tips

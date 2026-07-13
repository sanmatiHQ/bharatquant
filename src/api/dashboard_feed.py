"""Aggregated live feed for public dashboard."""
from __future__ import annotations

import json
import time
from typing import Any

from ..db.database import DB
from ..ops.agent_state import load_agent_status
from ..ops.budget_gate import budget_status
from ..ops.daily_pnl import portfolio_state
from ..ops.decision_review import build_learning_review
from ..ops.healthchecks import check_token, check_token_fast
from ..ops.market_pulse import load_live_pulse
from ..ops.session_ledger import build_session_ledger
from ..ops.trading_phase import evaluate_live_gate


def build_live_feed(db: DB, *, fast: bool = False) -> dict[str, Any]:
    """Single payload for dashboard polling — reduces round-trips."""
    now = int(time.time())
    kite_ok = check_token_fast() if fast else check_token(live=True)
    pulse = load_live_pulse(db, kite_ok=kite_ok)
    agent = load_agent_status(db)
    portfolio = portfolio_state(db)
    budget = budget_status(db)
    phase = evaluate_live_gate(db)
    learning = {} if fast else build_learning_review(db)
    session = build_session_ledger(db)

    conn = db._conn
    buy = float(conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY'").fetchone()[0])
    sell = float(conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='SELL'").fetchone()[0])
    unrealized = float(
        conn.execute("SELECT IFNULL(SUM((last_price-avg_price)*qty),0) FROM positions").fetchone()[0]
    )

    decisions = []
    dec_raw = conn.execute("SELECT v FROM settings WHERE k='agent_last_decision'").fetchone()
    if dec_raw:
        try:
            decisions.append(json.loads(dec_raw["v"]))
        except json.JSONDecodeError:
            pass

    ledger = [
        dict(r)
        for r in conn.execute(
            """
            SELECT ts, strategy_id, symbol, signal, confidence, executed, reason
            FROM strategy_ledger ORDER BY ts DESC LIMIT 30
            """
        ).fetchall()
    ]

    trades = [
        dict(r)
        for r in conn.execute(
            """
            SELECT ts, symbol, side, qty, price, amount, reason
            FROM trades ORDER BY ts DESC LIMIT 25
            """
        ).fetchall()
    ]

    positions = [
        dict(r)
        for r in conn.execute(
            "SELECT symbol, qty, avg_price, last_price, open_ts FROM positions WHERE qty > 0"
        ).fetchall()
    ]

    strategy_pnl = [
        dict(r)
        for r in conn.execute(
            "SELECT strategy_id, realized_pnl, trade_count FROM strategy_pnl ORDER BY trade_count DESC LIMIT 15"
        ).fetchall()
    ]

    activity = []
    for t in trades[:12]:
        activity.append(
            {
                "kind": "trade",
                "ts": t["ts"],
                "text": f"{t['side']} {t['qty']} {t['symbol']} @ ₹{t['price']:.2f}",
                "detail": t.get("reason") or "",
            }
        )
    for s in ledger[:15]:
        if s.get("executed"):
            tag = "EXEC"
        elif s.get("signal") in ("BUY", "SELL"):
            tag = s["signal"]
        else:
            tag = "SIG"
        activity.append(
            {
                "kind": "signal",
                "ts": s["ts"],
                "text": f"{tag} {s['strategy_id']} → {s['symbol']}",
                "detail": (s.get("reason") or f"conf={s.get('confidence', 0):.2f}").strip(),
            }
        )
    if decisions:
        d = decisions[0]
        activity.append(
            {
                "kind": "decision",
                "ts": d.get("ts", now),
                "text": f"{d.get('action', '?')} {d.get('symbol', '')} via {d.get('strategy', '')}",
                "detail": d.get("reason") or "",
            }
        )
    activity.sort(key=lambda x: x["ts"], reverse=True)
    activity = activity[:25]

    ctx = agent.get("context") or {}
    realized = sell - buy
    total_pnl = realized + unrealized

    def _setting(key: str):
        row = conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
        return row["v"] if row else None

    rl_meta_raw = _setting("rl_last_train_meta")
    eod_raw = _setting("eod_scan_latest")
    pre_raw = _setting("premarket_brief_latest")
    postm_raw = _setting("llm_postmortem_latest")
    rl_note_raw = _setting("rl_strategy_version_note")
    try:
        rl_last_train = json.loads(rl_meta_raw) if rl_meta_raw else None
    except json.JSONDecodeError:
        rl_last_train = None
    try:
        eod_scan = json.loads(eod_raw) if eod_raw else None
    except json.JSONDecodeError:
        eod_scan = None
    try:
        premarket_brief = json.loads(pre_raw) if pre_raw else None
    except json.JSONDecodeError:
        premarket_brief = None
    try:
        llm_postmortem = json.loads(postm_raw) if postm_raw else None
    except json.JSONDecodeError:
        llm_postmortem = None
    try:
        rl_strategy_note = json.loads(rl_note_raw) if rl_note_raw else None
    except json.JSONDecodeError:
        rl_strategy_note = None

    from ..intelligence.corporate_activity import load_corporate_activity
    from ..intelligence.xai_reasoner import build_xai_narrative
    from ..intelligence.sandbox_review import sandbox_snapshot_light
    from ..ops.sparkline_data import sparklines_for_symbols
    from ..ops.system_telemetry import build_system_telemetry

    engine_live = pulse.get("engine_heartbeat_age_sec") is not None and pulse["engine_heartbeat_age_sec"] < 120
    telemetry = build_system_telemetry(
        db,
        ws_live=bool(pulse.get("ws_live")),
        engine_live=engine_live,
        kite_ok=kite_ok,
        fast=fast,
    )
    xai = build_xai_narrative(db, ctx) if not fast else {
        "narrative": (
            f"PnL ₹{session['pnl']['total']:+,.0f} "
            f"(realized ₹{session['pnl']['realized']:+,.0f}, open ₹{session['pnl']['unrealized']:+,.0f}). "
            f"{session['trade_count']} trades logged. "
            f"{session['plan_for_tomorrow'][:280]}"
        ),
        "lines": [session["plan_for_tomorrow"]],
    }
    corporate = load_corporate_activity(db, lookback_days=7)
    from ..intelligence.institutional_learning import load_institutional_weights
    from ..intelligence.strategy_learning import load_strategy_learn_weights

    inst_weights = load_institutional_weights(db)
    strat_weights = load_strategy_learn_weights(db)
    signal_outcomes = db._conn.execute(
        "SELECT COUNT(*) c FROM strategy_signal_outcomes WHERE ret_15m IS NOT NULL"
    ).fetchone()["c"]
    learned_rules = db._conn.execute(
        "SELECT COUNT(*) c FROM strategy_discovery WHERE promoted=1"
    ).fetchone()["c"]
    inst_outcomes = db._conn.execute(
        "SELECT COUNT(*) c FROM corporate_event_outcomes WHERE ret_5d IS NOT NULL"
    ).fetchone()["c"]
    inst_rl = db._conn.execute("SELECT COUNT(*) c FROM rl_transitions").fetchone()["c"]
    inst_shp = db._conn.execute("SELECT COUNT(*) c FROM shareholding_snapshots").fetchone()["c"]
    institutional_learning = {
        "labeled_outcomes": int(inst_outcomes),
        "signal_outcomes": int(signal_outcomes),
        "promoted_rules": int(learned_rules),
        "rl_transitions": int(inst_rl),
        "shareholding_snapshots": int(inst_shp),
        "strategy_weights": {**(inst_weights.get("strategies") or {}), **(strat_weights.get("strategies") or {})},
        "unified_weights": strat_weights.get("strategies") or {},
        "pattern_count": len(inst_weights.get("patterns") or {}),
        "updated_ts": strat_weights.get("ts") or inst_weights.get("ts"),
    }
    sym_set = list({p["symbol"] for p in positions} | {q["symbol"] for q in pulse.get("live_quotes", [])})
    sparklines = {} if fast else sparklines_for_symbols(db, sym_set)

    return {
        "ts": now,
        "mode": phase.get("trading_mode", "paper"),
        "phase": phase.get("phase"),
        "live_gate_eligible": phase.get("live_gate_eligible"),
        "paper_return_pct": (phase.get("paper_performance") or {}).get("return_pct"),
        "engine_live": engine_live,
        "engine_phase": agent.get("engine_phase"),
        "ws_live": pulse.get("ws_live"),
        "kite_ok": kite_ok,
        "ticks_per_min": pulse.get("ticks_per_min", 0),
        "narrative": pulse.get("narrative"),
        "regime": ctx.get("regime", "NEUTRAL"),
        "fii_net_cr": ctx.get("fii_net_cr"),
        "gift_pct": ctx.get("gift_nifty_change_pct"),
        "llm_bias": ctx.get("llm_bias", 0),
        "india_vix": ctx.get("india_vix"),
        "session_phase": ctx.get("session_phase"),
        "nse_status": ctx.get("nse_status"),
        "market_open": ctx.get("market_open"),
        "ist_date": ctx.get("ist_date"),
        "ist_time": ctx.get("ist_time"),
        "minutes_to_close": ctx.get("minutes_to_close"),
        "fear_greed_index": ctx.get("fear_greed_index", 50),
        "sentiment_label": ctx.get("sentiment_label", "Neutral"),
        "recent_headlines": ctx.get("recent_headlines", [])[:6],
        "premarket_brief": premarket_brief,
        "llm_postmortem": llm_postmortem,
        "rl_last_train": rl_last_train,
        "eod_scan": eod_scan,
        "rl_strategy_note": rl_strategy_note,
        "futures_oi_chg": ctx.get("futures_oi_chg", 0),
        "cash": portfolio.get("cash", 0),
        "total_equity": portfolio.get("total_equity", 0),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(total_pnl, 2),
        "open_positions": pulse.get("open_positions", 0),
        "deployed_today": budget.get("deployed_today_inr", 0),
        "budget_max": budget.get("daily_max_inr", 0),
        "budget_base": budget.get("daily_base_inr", 0),
        "budget_rolled": budget.get("rolled_inr", 0),
        "budget_rollover_mode": budget.get("rollover_mode", "strict"),
        "budget_used_pct": budget.get("budget_used_pct", 0),
        "budget_pending": budget.get("pending_increase"),
        "budget_pending_expires_sec": budget.get("pending_expires_in_sec"),
        "last_decision": decisions[0] if decisions else None,
        "activity": activity,
        "tape": pulse.get("tape", []),
        "live_quotes": pulse.get("live_quotes", []),
        "positions": positions,
        "trades": trades,
        "signals": ledger,
        "strategy_pnl": strategy_pnl,
        "learning_tips": learning.get("improvement_tips", [])[:5],
        "supervisor_reason": agent.get("supervisor_reason"),
        "telemetry": telemetry,
        "xai": xai,
        "session": session,
        "corporate": corporate,
        "institutional_learning": institutional_learning,
        "sparklines": sparklines,
        "sandbox": sandbox_snapshot_light(db),
        "transport": "fast" if fast else "snapshot",
    }


def build_live_feed_fast(db: DB) -> dict[str, Any]:
    return build_live_feed(db, fast=True)

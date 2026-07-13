"""Explainable AI — plain-language agent reasoning for dashboard XAI panel."""
from __future__ import annotations

import json
from typing import Any

from ..db.database import DB
from .corporate_activity import corporate_narrative_lines, load_corporate_activity


def build_xai_narrative(db: DB, ctx: dict | None = None) -> dict[str, Any]:
    """Synthesize human-readable reasoning from last decision + macro context."""
    ctx = ctx or {}
    dec_raw = db._conn.execute("SELECT v FROM settings WHERE k='agent_last_decision'").fetchone()
    pre_raw = db._conn.execute("SELECT v FROM settings WHERE k='premarket_brief_latest'").fetchone()
    rl_raw = db._conn.execute("SELECT v FROM settings WHERE k='rl_last_train_meta'").fetchone()

    decision = json.loads(dec_raw["v"]) if dec_raw else None
    premarket = json.loads(pre_raw["v"]) if pre_raw else None
    rl_meta = json.loads(rl_raw["v"]) if rl_raw else None

    llm_bias = float(ctx.get("llm_bias", 0) or 0)
    fii = float(ctx.get("fii_net_cr", 0) or 0)
    gift = float(ctx.get("gift_nifty_change_pct", 0) or 0)
    vix = float(ctx.get("india_vix", 0) or 0)
    regime = str(ctx.get("regime", "NEUTRAL"))

    lines: list[str] = []

    buy = float(
        db._conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY'").fetchone()[0]
    )
    sell = float(
        db._conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='SELL'").fetchone()[0]
    )
    unreal = float(
        db._conn.execute("SELECT IFNULL(SUM((last_price-avg_price)*qty),0) FROM positions").fetchone()[0]
    )
    total_pnl = (sell - buy) + unreal
    equity_row = db._conn.execute("SELECT IFNULL(SUM(delta),0) c FROM cash_ledger").fetchone()
    cash = float(equity_row["c"]) if equity_row else 0.0
    pos_val = float(
        db._conn.execute(
            "SELECT IFNULL(SUM(last_price*qty),0) FROM positions WHERE qty > 0"
        ).fetchone()[0]
    )
    lines.append(
        f"Profit mission: equity ₹{cash + pos_val:,.0f}, PnL ₹{total_pnl:+,.0f} "
        f"(realized ₹{sell - buy:+,.0f}, open ₹{unreal:+,.0f})."
    )

    if premarket and premarket.get("text"):
        lines.append(f"Morning thesis: {premarket['text']}")

    if decision:
        action = decision.get("action", "?")
        sym = decision.get("symbol", "")
        strat = decision.get("strategy", "")
        reason = decision.get("reason", "")
        if action in ("BUY", "SELL") and sym:
            bias_note = "bullish macro tailwind" if llm_bias > 0.3 else "bearish macro headwind" if llm_bias < -0.3 else "neutral macro"
            fii_note = "FII net buyers" if fii > 50 else "FII net sellers" if fii < -50 else "mixed FII flow"
            lines.append(
                f"{action} {sym} via {strat} — LLM bias {llm_bias:+.2f} ({bias_note}), "
                f"GIFT {gift:+.2f}%, {fii_note}, VIX {vix:.1f}, regime {regime}."
            )
            if reason and reason != decision.get("signal"):
                lines.append(f"Execution detail: {reason}")
        elif action == "VETO":
            lines.append(f"VETO on {sym or 'signal'}: {reason or 'risk gate blocked entry'}.")
        elif action in ("PREMARKET", "POSTMARKET"):
            lines.append(reason or f"{action} routine completed.")
        elif reason:
            lines.append(reason)
    elif premarket:
        lines.append(premarket.get("text", "Awaiting first trade decision."))
    else:
        lines.append(
            f"Scanning watchlist — LLM bias {llm_bias:+.2f}, GIFT {gift:+.2f}%, "
            f"VIX {vix:.1f}. No execution yet this session."
        )

    if rl_meta:
        promoted = rl_meta.get("promoted")
        shadow = rl_meta.get("shadow") or {}
        lines.append(
            f"RL policy: {'promoted' if promoted else 'held stable'} "
            f"(shadow {shadow.get('reason', 'n/a')}, abnormal_day={rl_meta.get('abnormal_day', False)})."
        )

    post_raw = db._conn.execute("SELECT v FROM settings WHERE k='llm_postmortem_latest'").fetchone()
    if post_raw:
        try:
            pm = json.loads(post_raw["v"])
            if pm.get("summary"):
                lines.append(f"Post-mortem: {pm['summary']}")
        except json.JSONDecodeError:
            pass

    corp = load_corporate_activity(db, lookback_days=7)
    for line in corporate_narrative_lines(corp):
        lines.append(f"Corporate intel: {line}")

    return {
        "narrative": " ".join(lines),
        "lines": lines,
        "llm_bias": llm_bias,
        "regime": regime,
        "last_action": decision.get("action") if decision else None,
        "corporate": corp,
    }

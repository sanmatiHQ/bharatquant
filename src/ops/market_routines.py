"""
IST wall-clock pre/post market routines — dashboard sync + learning loop.

Pre-market 08:45: LLM macro burst, Latest agent decision push, VIX budget auto-approve.
Post-market 16:15: slippage analysis, guarded RL train, strategy version row, LLM post-mortem.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from ..db.database import DB
from ..ops.agent_state import persist_decision
from ..ops.budget_gate import auto_approve_budget_if_vix_safe
from ..ops.slippage_analysis import analyze_today_slippage
from ..ops.vix_controls import vix_from_db

logger = logging.getLogger("bharatquant.market_routines")

_TZ = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
KEY_PREMARKET_DAY = "premarket_routine_day"
KEY_POSTMARKET_DAY = "postmarket_routine_day"


def _ist_now() -> datetime:
    return datetime.now(_TZ)


def _day_key() -> str:
    return _ist_now().strftime("%Y-%m-%d")


def _time_hm() -> tuple[int, int]:
    n = _ist_now()
    return n.hour, n.minute


def _bias_label(bias: float) -> str:
    if bias >= 0.35:
        return "Bullish"
    if bias <= -0.35:
        return "Bearish"
    return "Neutral"


def _fii_label(fii: float) -> str:
    if fii > 50:
        return "FII Net Buyers"
    if fii < -50:
        return "FII Net Sellers"
    return "FII Mixed"


async def run_premarket_routine(db: DB, ctx: Any, rl_agent: Any = None) -> dict[str, Any]:
    """08:45 burst — LLM bias, regime RL hot-swap, dashboard decision text, VIX budget gate."""
    from ..ingest.llm_macro import compute_llm_bias
    from ..agent.regime_classifier import classify_regime_from_prices, recent_index_closes

    import numpy as np

    ctx_dict = {
        "fii_net_cr": getattr(ctx, "fii_net_cr", 0),
        "dii_net_cr": getattr(ctx, "dii_net_cr", 0),
        "gift_pct": getattr(ctx, "gift_nifty_change_pct", 0),
        "india_vix": getattr(ctx, "india_vix", 0) or vix_from_db(db),
        "futures_oi_chg": getattr(ctx, "futures_oi_chg", 0),
    }
    bias = await compute_llm_bias(db, ctx_dict)
    ctx.llm_bias = bias

    gift = float(getattr(ctx, "gift_nifty_change_pct", 0) or 0)
    fii = float(getattr(ctx, "fii_net_cr", 0) or 0)
    vix = float(getattr(ctx, "india_vix", 0) or vix_from_db(db))
    closes = recent_index_closes(db)
    if closes:
        rs = classify_regime_from_prices(np.array(closes, dtype=np.float64), vix)
        ctx.regime = rs.label
    regime_swap: dict[str, Any] = {}
    if rl_agent is not None:
        regime_swap = rl_agent.hot_swap_regime_policy(getattr(ctx, "regime", "SIDEWAYS"))
    now = _ist_now()
    stamp = now.strftime("%I:%M %p").lstrip("0")

    budget_result = auto_approve_budget_if_vix_safe(db)
    budget_note = (
        f"Budget auto-approved (VIX {vix:.1f} within safe limits)."
        if budget_result.get("ok")
        else f"Budget hold — {budget_result.get('reason', 'VIX outside limits')}."
    )
    scaling = "Long scaling enabled" if bias >= 0.25 else "Defensive sizing" if bias <= -0.25 else "Balanced sizing"

    narrative = (
        f"[{stamp}] Bias set to {bias:+.2f} ({_bias_label(bias)}). "
        f"GIFT Nifty {gift:+.2f}%, {_fii_label(fii)}. "
        f"VIX {vix:.1f}. Regime {getattr(ctx, 'regime', 'NEUTRAL')}. {scaling}. {budget_note}"
    )
    if regime_swap.get("loaded"):
        narrative += f" RL policy: {regime_swap.get('bucket')}."

    persist_decision(
        db,
        {
            "action": "PREMARKET",
            "strategy": "llm_macro",
            "symbol": "MACRO",
            "signal": _bias_label(bias).upper(),
            "reason": narrative,
            "llm_bias": bias,
            "gift_pct": gift,
            "india_vix": vix,
            "budget_auto": budget_result.get("ok"),
        },
    )
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("premarket_brief_latest", json.dumps({"ts": int(time.time()), "text": narrative, "bias": bias})),
        )
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_PREMARKET_DAY, _day_key()),
        )

    logger.info(
        "premarket_routine_done",
        extra={"bias": bias, "budget": budget_result.get("ok"), "regime": getattr(ctx, "regime", ""), "rl": regime_swap},
    )
    return {"ok": True, "bias": bias, "narrative": narrative, "budget": budget_result, "regime_swap": regime_swap}


def _update_rl_strategy_row(db: DB, version: str, meta: dict) -> None:
    promoted = meta.get("promoted", False)
    suffix = "Promoted" if promoted else "Reverted"
    sid = f"PPO_{version}_Adaptive"
    ts = int(time.time())
    note = f"Weights {suffix} · LR {meta.get('learning_rate', '?')} · shadow {meta.get('shadow', {}).get('reason', 'n/a')}"
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO strategy_pnl(strategy_id, realized_pnl, trade_count, updated_ts)
            VALUES (?, 0, 0, ?)
            ON CONFLICT(strategy_id) DO UPDATE SET
              trade_count = strategy_pnl.trade_count + 1,
              updated_ts = excluded.updated_ts
            """,
            (sid, ts),
        )
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("rl_strategy_version_note", json.dumps({"strategy_id": sid, "note": note, "ts": ts, "meta": meta})),
        )


async def run_postmarket_routine(db: DB, *, force: bool = False) -> dict[str, Any]:
    """16:15 — slippage, guarded RL, regime policies, strategy version, post-mortem."""
    from ..intelligence.llm_postmortem import run_llm_postmortem
    from ..intelligence.sandbox_review import build_sandbox_review
    from ..ops.gcs_store import sync_rl_model
    from ..rl.training_guardrails import (
        guarded_train_and_promote,
        already_trained_today,
        train_regime_policies,
    )

    slippage = analyze_today_slippage(db)
    rl_meta: dict[str, Any] = {"skipped": True, "reason": "already_trained"}
    version = os.getenv("RL_ACTIVE_VERSION", "ppo_v1")
    model_dir = os.getenv("RL_MODEL_DIR", "models/rl")

    if force or not already_trained_today(db):
        rl_meta = await asyncio.to_thread(guarded_train_and_promote, db, model_dir, version)
        if rl_meta.get("promoted") and rl_meta.get("train", {}).get("status") == "ok":
            await asyncio.to_thread(sync_rl_model, model_dir, version)
        regime_meta = await asyncio.to_thread(train_regime_policies, db, model_dir, version)
        rl_meta["regime_policies"] = regime_meta
        await asyncio.to_thread(build_sandbox_review, db, recompute=True)
    _update_rl_strategy_row(db, version, rl_meta)

    postmortem = await run_llm_postmortem(db)

    narrative = (
        f"Post-market complete: {slippage.get('trade_count', 0)} trades, "
        f"avg slippage {slippage.get('avg_abs_slippage_bps', 0)} bps. "
        f"RL {'promoted' if rl_meta.get('promoted') else 'held/reverted'}."
    )
    persist_decision(
        db,
        {
            "action": "POSTMARKET",
            "strategy": f"PPO_{version}",
            "symbol": "SESSION",
            "signal": "LEARN",
            "reason": narrative,
            "slippage": slippage.get("avg_abs_slippage_bps"),
            "rl_promoted": rl_meta.get("promoted"),
        },
    )
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_POSTMARKET_DAY, _day_key()),
        )

    logger.info("postmarket_routine_done", extra={"trades": slippage.get("trade_count"), "rl": rl_meta.get("promoted")})
    return {
        "ok": True,
        "slippage": slippage,
        "rl": rl_meta,
        "postmortem": postmortem,
        "narrative": narrative,
    }


async def market_routines_loop(
    db: DB,
    ctx: Any,
    *,
    rl_agent: Any = None,
    publish_activity: Optional[Callable[[str], None]] = None,
    interval_sec: float = 30.0,
) -> None:
    """Background IST scheduler — runs once per weekday at configured times."""
    pre_h, pre_m = [int(x) for x in os.getenv("PREMARKET_ROUTINE_TIME", "8:45").split(":")]
    post_h, post_m = [int(x) for x in os.getenv("POSTMARKET_ROUTINE_TIME", "16:15").split(":")]

    while True:
        try:
            now = _ist_now()
            if now.weekday() < 5:
                day = _day_key()
                hm = (now.hour, now.minute)
                pre_done = db._conn.execute(
                    "SELECT v FROM settings WHERE k=?", (KEY_PREMARKET_DAY,)
                ).fetchone()
                post_done = db._conn.execute(
                    "SELECT v FROM settings WHERE k=?", (KEY_POSTMARKET_DAY,)
                ).fetchone()

                if hm == (pre_h, pre_m) and (not pre_done or pre_done["v"] != day):
                    if publish_activity:
                        publish_activity("Pre-market: running LLM macro + budget gate…")
                    await run_premarket_routine(db, ctx, rl_agent=rl_agent)
                    await asyncio.sleep(61)

                elif hm == (post_h, post_m) and (not post_done or post_done["v"] != day):
                    if publish_activity:
                        publish_activity("Post-market: slippage + RL train + post-mortem…")
                    await run_postmarket_routine(db)
                    await asyncio.sleep(61)
        except Exception:
            logger.exception("market_routines_error")
        await asyncio.sleep(interval_sec)

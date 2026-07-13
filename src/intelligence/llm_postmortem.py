"""LLM post-mortem — morning thesis vs actual session outcome."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db.database import DB
from ..ingest.llm_macro import llm_enabled

logger = logging.getLogger("bharatquant.llm_postmortem")

IST = timezone(timedelta(hours=5, minutes=30))


def _today_start_ts() -> int:
    now = datetime.now(IST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def _build_postmortem_prompt(db: DB, ctx: dict, trades: list, slippage: dict) -> str:
    buy = float(
        db._conn.execute(
            "SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY' AND ts>=?",
            (_today_start_ts(),),
        ).fetchone()[0]
    )
    sell = float(
        db._conn.execute(
            "SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='SELL' AND ts>=?",
            (_today_start_ts(),),
        ).fetchone()[0]
    )
    pnl = sell - buy
    return (
        "You are reviewing an Indian NSE paper-trading session. "
        "Output ONLY valid JSON: {summary (2-3 sentences), score (-1..+1 how well thesis matched), "
        "lessons (array of short strings)}.\n\n"
        f"Morning LLM bias: {ctx.get('llm_bias', 0)}\n"
        f"GIFT Nifty %: {ctx.get('gift_nifty_change_pct', 0)}\n"
        f"FII net cr: {ctx.get('fii_net_cr', 0)}\n"
        f"India VIX: {ctx.get('india_vix', 0)}\n"
        f"Trades today: {len(trades)}\n"
        f"Gross PnL (sell-buy): ₹{pnl:.0f}\n"
        f"Avg slippage bps: {slippage.get('avg_abs_slippage_bps', 0)}\n"
        f"Trade symbols: {[t.get('symbol') for t in trades[:8]]}\n"
    )


async def run_llm_postmortem(db: DB) -> dict[str, Any]:
    if not llm_enabled():
        return {"ok": False, "reason": "llm_disabled"}
    ctx_raw = db._conn.execute("SELECT v FROM settings WHERE k='agent_context'").fetchone()
    ctx = json.loads(ctx_raw["v"]) if ctx_raw else {}
    slip_raw = db._conn.execute("SELECT v FROM settings WHERE k='slippage_summary_latest'").fetchone()
    slippage = json.loads(slip_raw["v"]) if slip_raw else {}
    trades = db._conn.execute(
        "SELECT symbol, side, qty, price, amount FROM trades WHERE ts>=? ORDER BY ts",
        (_today_start_ts(),),
    ).fetchall()
    trades_list = [dict(r) for r in trades]

    from ..ingest.llm_macro import (
        _call_anthropic,
        _call_gemini,
        _call_openai_compat,
        _call_vertex_gemini,
    )

    prompt = _build_postmortem_prompt(db, ctx, trades_list, slippage)
    try:
        text = await _call_vertex_gemini(prompt)
        if not text:
            text = await _call_gemini(prompt)
        if not text:
            text = await _call_openai_compat(prompt)
        if not text:
            text = await _call_anthropic(prompt)
        if not text:
            return {"ok": False, "reason": "llm_unavailable"}
    except Exception as exc:
        logger.warning("postmortem_llm_failed", extra={"err": str(exc)})
        return {"ok": False, "reason": str(exc)}

    detail: dict = {"raw": text[:800]}
    try:
        import re

        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        m = re.search(r"\{[^{}]*\"summary\"[^{}]*\}", cleaned, re.DOTALL)
        detail = json.loads(m.group() if m else cleaned)
    except Exception:
        detail = {"summary": text[:400], "score": 0.0, "lessons": []}

    payload = {"ts": int(time.time()), **detail}
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("llm_postmortem_latest", json.dumps(payload)),
        )
    logger.info("llm_postmortem_done", extra={"score": detail.get("score")})
    return {"ok": True, **payload}

"""Holistic fast decision — one ranked choice every N seconds from full picture."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from ..db.database import DB
from ..ops.trade_sizing import can_buy_whole_share, deploy_cap_inr
from ..ops.cost_gate import min_qty_for_cost_edge
from ..costs.cost_engine import CostEngine
from ..strategies.base import MarketContext, Signal

logger = logging.getLogger("bharatquant.fast_snapshot")


def _today_start_ts() -> int:
    tz = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
    now = datetime.now(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


def _session_open(db: DB, sym: str, ctx: MarketContext, ltp: float) -> float:
    if sym in ctx.session_open and ctx.session_open[sym] > 0:
        return float(ctx.session_open[sym])
    ref = ctx.orb_low.get(sym) or ctx.orb_high.get(sym)
    if ref and ref > 0:
        return float(ref)
    row = db._conn.execute(
        """
        SELECT open FROM bar_log
        WHERE symbol=? AND interval='5m' AND ts >= ?
        ORDER BY ts ASC LIMIT 1
        """,
        (sym, _today_start_ts()),
    ).fetchone()
    if row and float(row["open"]) > 0:
        return float(row["open"])
    return ltp


def build_holistic_signal(db: DB, ctx: MarketContext) -> Optional[tuple[Signal, float]]:
    """
    Rank universe by screening + intraday move + macro; size by remaining budget (not stock price cap).
    Returns (signal, ltp) or None.
    """
    max_pos = int(os.getenv("MAX_POSITIONS", "8"))
    open_pos = int(
        db._conn.execute("SELECT COUNT(*) c FROM positions WHERE qty > 0").fetchone()["c"]
    )
    if open_pos >= max_pos:
        return None

    held = {
        r["symbol"]
        for r in db._conn.execute("SELECT symbol FROM positions WHERE qty > 0").fetchall()
    }

    run_ts_row = db._conn.execute("SELECT MAX(run_ts) t FROM screening_results").fetchone()
    if not run_ts_row or not run_ts_row["t"]:
        return None

    candidates = db._conn.execute(
        """
        SELECT s.symbol, s.momentum_score,
               (SELECT ltp FROM tick_log t WHERE t.symbol=s.symbol ORDER BY ts DESC LIMIT 1) AS ltp
        FROM screening_results s
        WHERE s.run_ts = ?
        ORDER BY s.momentum_score DESC
        LIMIT ?
        """,
        (run_ts_row["t"], int(os.getenv("FAST_SNAPSHOT_CANDIDATES", "80"))),
    ).fetchall()

    fii = float(ctx.fii_net_cr or 0)
    if fii == 0 and db:
        try:
            import json

            raw = db._conn.execute("SELECT v FROM settings WHERE k='agent_context'").fetchone()
            if raw:
                fii = float(json.loads(raw["v"]).get("fii_net_cr", 0))
        except Exception:
            pass
    gift = float(ctx.gift_nifty_change_pct or 0)
    macro_boost = 1.0
    if fii > 300:
        macro_boost += 0.12
    elif fii < -500:
        macro_boost -= 0.15
    if gift > 0.15:
        macro_boost += 0.08
    elif gift < -0.2:
        macro_boost -= 0.1

    llm_bias = float(getattr(ctx, "llm_bias", 0) or 0)
    macro_boost *= 1.0 + llm_bias * 0.15

    futures_oi = float(getattr(ctx, "futures_oi_chg", 0) or 0)
    if futures_oi > 2.0:
        macro_boost += 0.05
    elif futures_oi < -2.0:
        macro_boost -= 0.05

    cash = float(
        db._conn.execute("SELECT IFNULL(SUM(delta),0) FROM cash_ledger").fetchone()[0]
    )
    deploy_cap = deploy_cap_inr(db, cash)
    if deploy_cap <= 0:
        return None

    costs = CostEngine(slippage_bps=int(os.getenv("SLIPPAGE_BPS", "4")))

    pace = os.getenv("BUDGET_PACE", "patient").lower()
    score_floor = 0.35
    if pace == "fill_today" and _minutes_to_close() < 90:
        score_floor = 0.28

    best: tuple[float, str, float, str] | None = None
    for row in candidates:
        sym = str(row["symbol"])
        ltp = float(row["ltp"] or 0)
        if ltp <= 0 or sym in held or not can_buy_whole_share(ltp, deploy_cap):
            continue
        min_q = min_qty_for_cost_edge(costs, ltp, deploy_cap)
        if min_q <= 0 or deploy_cap < min_q * ltp:
            continue
        open_px = _session_open(db, sym, ctx, ltp)
        move_pct = (ltp - open_px) / open_px * 100 if open_px > 0 else 0.0
        mom = float(row["momentum_score"] or 0)
        spread = float(getattr(ctx, "spread_bps", {}).get(sym, 0) or 0)
        obi = float(getattr(ctx, "orderbook_imbalance", {}).get(sym, 0) or 0)
        atr_bps = float(getattr(ctx, "tick_atr_bps", {}).get(sym, 0) or 0)
        spread_penalty = 1.0 - min(0.25, spread / 100.0)
        obi_boost = 1.0 + max(-0.12, min(0.12, obi * 0.15))
        atr_penalty = 1.0 - min(0.2, atr_bps / 80.0)
        from ..intelligence.corporate_activity import corporate_profit_tilt

        corp_mult, corp_reasons = corporate_profit_tilt(sym, ctx)
        score = (
            mom
            * macro_boost
            * spread_penalty
            * obi_boost
            * atr_penalty
            * corp_mult
            * (1.0 + max(0.0, move_pct) * 0.15)
        )
        if move_pct < -0.35:
            score *= 0.5
        reason = (
            f"holistic mom={mom:.2f} move={move_pct:.2f}% fii={fii:.0f} gift={gift:.2f}% "
            f"llm={llm_bias:+.2f} obi={obi:+.2f} atr={atr_bps:.0f}bps corp={corp_mult:.2f}"
        )
        if corp_reasons:
            reason += f" ({','.join(corp_reasons[:2])})"
        if best is None or score > best[0]:
            best = (score, sym, ltp, reason)

    if not best or best[0] < score_floor:
        return None

    score, sym, ltp, reason = best
    conf = min(0.92, 0.55 + score * 0.25)
    sig = Signal("fast_snapshot", sym, "BUY", "MIS", conf, reason)
    logger.info("fast_snapshot_pick", extra={"symbol": sym, "ltp": ltp, "score": score, "conf": conf})
    return sig, ltp


def is_fast_path_enabled() -> bool:
    return os.getenv("FAST_PATH_ENTRIES", "true").lower() in ("1", "true", "yes")


def _minutes_to_close() -> float:
    tz = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
    now = datetime.now(tz)
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return max(0.0, (close - now).total_seconds() / 60.0)


def is_market_session() -> bool:
    tz = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
    now = datetime.now(tz)
    if now.weekday() >= 5:
        return False
    hour = now.hour + now.minute / 60.0
    return 9.2 <= hour <= 15.45


async def run_fast_decision_loop(
    db: DB,
    ctx: MarketContext,
    publish,
    *,
    interval_sec: float | None = None,
) -> None:
    """Publish FAST_SNAPSHOT events on interval — holistic entry decisions."""
    if not is_fast_path_enabled():
        return
    from ..events.types import EventType, MarketEvent

    sec = interval_sec or float(os.getenv("FAST_DECISION_SEC", "8"))
    logger.info("fast_decision_loop_started", extra={"interval_sec": sec})
    while True:
        try:
            if is_market_session():
                picked = build_holistic_signal(db, ctx)
                if picked:
                    sig, ltp = picked
                    await publish(
                        MarketEvent(
                            type=EventType.FAST_SNAPSHOT,
                            symbol=sig.symbol,
                            price=ltp,
                            ts=int(time.time()),
                            payload={
                                "strategy_id": sig.strategy_id,
                                "action": sig.action,
                                "rail": sig.rail,
                                "confidence": sig.confidence,
                                "reason": sig.reason,
                            },
                        )
                    )
        except Exception:
            logger.exception("fast_snapshot_error")
        await asyncio.sleep(sec)

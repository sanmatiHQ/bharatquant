"""Shadow backtest — compare RL policies on 5m bar_log before promotion."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from ..costs.cost_engine import CostEngine
from ..db.database import DB
from .ppo_trainer import PPOPolicy
from .state_encoder import STATE_DIM

logger = logging.getLogger("bharatquant.shadow_backtest")

_TZ = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))


def _lookback_cutoff_ts(days: int) -> int:
    return int(time.time()) - days * 86400


def _symbols_for_eval(db: DB, limit: int = 12) -> list[str]:
    rows = db._conn.execute(
        """
        SELECT symbol FROM screening_results
        WHERE run_ts = (SELECT MAX(run_ts) FROM screening_results)
        ORDER BY momentum_score DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    syms = [str(r["symbol"]) for r in rows]
    if syms:
        return syms
    rows = db._conn.execute(
        "SELECT DISTINCT symbol FROM bar_log WHERE interval='5m' ORDER BY symbol LIMIT ?",
        (limit,),
    ).fetchall()
    return [str(r["symbol"]) for r in rows]


def _bars_for_symbol(db: DB, symbol: str, cutoff_ts: int) -> list[dict]:
    cur = db._conn.execute(
        """
        SELECT ts, open, high, low, close, volume FROM bar_log
        WHERE symbol=? AND interval='5m' AND ts >= ?
        ORDER BY ts ASC
        """,
        (symbol, cutoff_ts),
    )
    return [dict(r) for r in cur.fetchall()]


def _encode_bar_state(
    closes: list[float],
    idx: int,
    *,
    score: float = 0.5,
) -> np.ndarray:
    """Lightweight state from 5m close series (no live ctx required)."""
    if idx < 2:
        mom = 0.0
    else:
        c0 = closes[idx - 3] if idx >= 3 else closes[0]
        c1 = closes[idx]
        mom = (c1 - c0) / c0 if c0 > 0 else 0.0
    d = {
        "regime": "NEUTRAL",
        "fii_net_cr": 0,
        "gift_nifty_change_pct": 0,
        "india_vix": 15,
        "llm_bias": 0,
    }
    from .state_encoder import encode_state_from_dict

    vec = encode_state_from_dict(d, score=float(np.clip(mom * 10 + score * 0.5, -1, 1)))
    arr = np.array(vec[:STATE_DIM], dtype=np.float64)
    if len(arr) < STATE_DIM:
        arr = np.pad(arr, (0, STATE_DIM - len(arr)))
    return arr


def evaluate_policy_on_bars(
    db: DB,
    policy_path: Path,
    *,
    lookback_days: int | None = None,
    max_symbols: int | None = None,
) -> dict:
    """
    Simulate policy on stored 5m bars — net reward after simple cost model.
    Higher score = better shadow performance.
    """
    lookback = lookback_days or int(os.getenv("RL_SHADOW_LOOKBACK_DAYS", "30"))
    max_sym = max_symbols or int(os.getenv("RL_SHADOW_MAX_SYMBOLS", "12"))
    if not policy_path.exists():
        return {"score": 0.0, "bars": 0, "symbols": 0, "reason": "missing_policy"}

    policy = PPOPolicy.load(policy_path)
    costs = CostEngine(slippage_bps=int(os.getenv("SLIPPAGE_BPS", "4")))
    cutoff = _lookback_cutoff_ts(lookback)
    symbols = _symbols_for_eval(db, max_sym)
    total_reward = 0.0
    total_bars = 0
    sym_used = 0

    for sym in symbols:
        bars = _bars_for_symbol(db, sym, cutoff)
        if len(bars) < 40:
            continue
        sym_used += 1
        closes = [float(b["close"]) for b in bars]
        position = 0
        entry_px = 0.0

        for i in range(10, len(bars) - 1):
            state = _encode_bar_state(closes, i)
            action, _ = policy.act(state)
            px = closes[i]
            nxt = closes[i + 1]
            ret = (nxt - px) / px if px > 0 else 0.0

            if action == 1 and position == 0:  # buy
                fee_pct = costs.round_trip_cost_inr(1, px) / max(px, 1) * 0.5
                position = 1
                entry_px = px
                total_reward -= fee_pct
            elif action == 2 and position == 1:  # sell
                gross = (px - entry_px) / entry_px if entry_px > 0 else 0.0
                fee_pct = costs.round_trip_cost_inr(1, px) / max(px, 1) * 0.5
                total_reward += gross - fee_pct
                position = 0
                entry_px = 0.0
            elif position == 1:
                total_reward += ret * 0.25
            total_bars += 1

    score = float(total_reward)
    return {
        "score": score,
        "bars": total_bars,
        "symbols": sym_used,
        "lookback_days": lookback,
        "policy": str(policy_path),
    }


def compare_policies(
    db: DB,
    stable_path: Path,
    candidate_path: Path,
) -> dict:
    """Return comparison; candidate must not be significantly worse than stable."""
    tol_pct = float(os.getenv("RL_SHADOW_MAX_REGRESSION_PCT", "2.0"))
    stable = evaluate_policy_on_bars(db, stable_path)
    candidate = evaluate_policy_on_bars(db, candidate_path)
    s = stable["score"]
    c = candidate["score"]
    # If stable has near-zero history, allow promote when candidate has data
    if stable["bars"] < 100 and candidate["bars"] >= 100:
        passed = True
        reason = "stable_insufficient_history"
    elif s == 0 and c == 0:
        passed = True
        reason = "both_neutral"
    else:
        floor = s - abs(s) * (tol_pct / 100.0) - tol_pct / 100.0
        passed = c >= floor
        reason = "shadow_pass" if passed else "shadow_regression"
    return {
        "passed": passed,
        "reason": reason,
        "stable": stable,
        "candidate": candidate,
        "tolerance_pct": tol_pct,
    }

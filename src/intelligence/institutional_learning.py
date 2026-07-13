"""Learn institutional event profitability — bandit weights + RL transitions (no LLM)."""
from __future__ import annotations

import json
import logging
import math
import os
import time
from typing import Any

from ..db.database import DB
from ..intelligence.event_outcomes import label_pending_events
from ..rl.rl_buffer import RLBuffer
from ..rl.state_encoder import encode_state_from_dict, index_action

logger = logging.getLogger("bharatquant.institutional_learning")

KEY_WEIGHTS = "institutional_learn_weights"
KEY_RL_SEED_TS = "institutional_rl_seed_ts"
_MIN_SAMPLES = 3
_RL_VERSION = os.getenv("RL_ACTIVE_VERSION", "ppo_v1")

_STRATEGY_MAP = {
    ("INSIDER_FILING", "promoter", "buy"): "insider_cluster",
    ("INSIDER_FILING", "insider", "buy"): "insider_cluster",
    ("BLOCK_DEAL", "block_deal", "buy"): "bulk_accumulation",
    ("BLOCK_DEAL", "block_deal", "sell"): "bulk_distribution",
    ("SHAREHOLDING_UPDATE", "shareholding", "buy"): "institutional_flow",
    ("MF_HOLDING_UPDATE", "mf_holding", "buy"): "institutional_flow",
    ("BOARD_MEETING", "earnings", "neutral"): "calendar_activity",
    ("CORPORATE_ACTION", "dividend", "neutral"): "calendar_activity",
    ("CORPORATE_ACTION", "bonus", "neutral"): "calendar_activity",
    ("CORPORATE_ACTION", "split", "neutral"): "calendar_activity",
    ("CORPORATE_ACTION", "buyback", "neutral"): "calendar_activity",
    ("BSE_ANNOUNCEMENT", "corporate", "neutral"): "calendar_activity",
    ("NEWS_ALERT", "earnings", "neutral"): "calendar_activity",
}


def _pattern_key(event_type: str, category: str, side: str, entity_class: str) -> str:
    return f"{event_type}:{category}:{side}:{entity_class}"


def learn_institutional_weights(db: DB) -> dict[str, float]:
    """Aggregate labeled outcomes → pattern multipliers stored in settings."""
    rows = db._conn.execute(
        """
        SELECT event_type, category, side, entity_class, ret_5d, ret_20d
        FROM corporate_event_outcomes
        WHERE ret_5d IS NOT NULL
        """
    ).fetchall()
    buckets: dict[str, list[float]] = {}
    for r in rows:
        key = _pattern_key(
            str(r["event_type"]),
            str(r["category"] or ""),
            str(r["side"] or ""),
            str(r["entity_class"] or "other"),
        )
        ret = float(r["ret_5d"])
        buckets.setdefault(key, []).append(ret)

    weights: dict[str, float] = {}
    for key, rets in buckets.items():
        if len(rets) < _MIN_SAMPLES:
            continue
        avg = sum(rets) / len(rets)
        win = sum(1 for x in rets if x > 0) / len(rets)
        # Multiplier ~0.85..1.15 from historical edge
        edge = math.tanh(avg / 8.0) * 0.12 + (win - 0.5) * 0.2
        weights[key] = round(max(0.75, min(1.25, 1.0 + edge)), 4)

    strategy_weights: dict[str, float] = {}
    for (et, cat, side), sid in _STRATEGY_MAP.items():
        hits = [w for k, w in weights.items() if k.startswith(f"{et}:{cat}:{side}:")]
        if hits:
            strategy_weights[sid] = round(sum(hits) / len(hits), 4)

    payload = {"patterns": weights, "strategies": strategy_weights, "ts": int(time.time()), "n": len(rows)}
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_WEIGHTS, json.dumps(payload)),
        )
    logger.info(
        "institutional_weights_updated",
        extra={"patterns": len(weights), "strategies": len(strategy_weights), "samples": len(rows)},
    )
    return strategy_weights


def load_institutional_weights(db: DB) -> dict[str, Any]:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_WEIGHTS,)).fetchone()
    if not row:
        return {"patterns": {}, "strategies": {}}
    try:
        return json.loads(row["v"])
    except json.JSONDecodeError:
        return {"patterns": {}, "strategies": {}}


def pattern_multiplier(
    weights: dict[str, Any],
    *,
    event_type: str,
    category: str,
    side: str,
    entity_class: str,
) -> tuple[float, str | None]:
    patterns = weights.get("patterns") or {}
    key = _pattern_key(event_type, category, side, entity_class)
    mult = float(patterns.get(key, 1.0))
    if mult != 1.0:
        return mult, f"learned_{key}"
    # Fallback: strategy-level weight
    strategies = weights.get("strategies") or {}
    for (et, cat, sd), sid in _STRATEGY_MAP.items():
        if et == event_type and cat == category and sd == side:
            sm = float(strategies.get(sid, 1.0))
            if sm != 1.0:
                return sm, f"learned_strategy_{sid}"
    return 1.0, None


def refresh_context_learning(db: DB, ctx: Any) -> dict[str, Any]:
    """Label → learn → push weights onto MarketContext (delegates to unified learner)."""
    from .strategy_learning import refresh_all_learning

    return refresh_all_learning(db, ctx)


def seed_rl_transitions_from_outcomes(db: DB) -> dict[str, int]:
    """Synthetic RL transitions from labeled institutional events."""
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_RL_SEED_TS,)).fetchone()
    since = int(json.loads(row["v"])) if row else 0
    rows = db._conn.execute(
        """
        SELECT * FROM corporate_event_outcomes
        WHERE labeled_ts > ? AND ret_5d IS NOT NULL
        ORDER BY labeled_ts ASC LIMIT 200
        """,
        (since,),
    ).fetchall()
    if not rows:
        return {"pushed": 0}

    buffer = RLBuffer(db)
    pushed = 0
    max_ts = since
    for r in rows:
        side = str(r["side"] or "buy")
        ret = float(r["ret_5d"])
        reward = ret / 5.0 if side == "buy" else -ret / 5.0
        reward = max(-1.0, min(1.0, reward))
        entity = str(r["entity_class"] or "other")
        state = encode_state_from_dict(
            {
                "regime": "NEUTRAL",
                "fii_net_cr": 1.0 if entity == "fii" else 0.0,
                "gift_nifty_change_pct": 0.0,
                "india_vix": 15.0,
                "llm_bias": 0.0,
                "obi": 0.2 if side == "buy" else -0.2,
            },
            score=reward,
            confidence=0.7,
            has_symbol=True,
        )
        action = index_action(1 if side == "buy" else 2)
        next_state = encode_state_from_dict({"regime": "NEUTRAL"}, score=reward, confidence=0.5)
        buffer.push(
            _RL_VERSION,
            str(r["symbol"]),
            {str(i): v for i, v in enumerate(state)},
            action,
            reward,
            {str(i): v for i, v in enumerate(next_state)},
            done=True,
        )
        pushed += 1
        max_ts = max(max_ts, int(r["labeled_ts"] or 0))

    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_RL_SEED_TS, json.dumps(max_ts)),
        )
    logger.info("institutional_rl_seeded", extra={"pushed": pushed})
    return {"pushed": pushed}

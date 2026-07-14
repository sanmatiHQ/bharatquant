"""Unified strategy learning — every signal, discovery rule, and trade feeds the agent."""
from __future__ import annotations

import json
import logging
import math
import os
import time
from typing import Any

from ..db.database import DB
from ..intelligence.event_outcomes import label_pending_events
from ..intelligence.institutional_learning import (
    learn_institutional_weights,
    load_institutional_weights,
    seed_rl_transitions_from_outcomes,
)
from ..rl.rl_buffer import RLBuffer
from ..rl.state_encoder import encode_state_from_dict, index_action
from ..strategies.custom_rules import CustomRuleSpec, CustomRuleStrategy
from ..events.types import EventType

logger = logging.getLogger("bharatquant.strategy_learning")

KEY_STRATEGY_WEIGHTS = "strategy_learn_weights"
KEY_LEARNED_CUSTOM = "learned_custom_rules"
KEY_RL_STRATEGY_SEED_TS = "strategy_rl_seed_ts"
_RL_VERSION = os.getenv("RL_ACTIVE_VERSION", "ppo_v1")
_H5M_SEC = 300
_H15_SEC = 900
_H1D_SEC = 86400
_MIN_SAMPLES = 5


def _price_near(db: DB, symbol: str, ts: int, *, window: int = 7200) -> float | None:
    sym = symbol.replace("NSE:", "")
    row = db._conn.execute(
        """
        SELECT ltp FROM tick_log
        WHERE symbol=? AND ts BETWEEN ? AND ?
        ORDER BY ABS(ts - ?) LIMIT 1
        """,
        (sym, ts - window, ts + window, ts),
    ).fetchone()
    if row:
        return float(row["ltp"])
    row = db._conn.execute(
        "SELECT close FROM bar_log WHERE symbol=? AND ts <= ? ORDER BY ts DESC LIMIT 1",
        (sym, ts + window),
    ).fetchone()
    return float(row["close"]) if row else None


def _forward_return_pct(db: DB, symbol: str, entry_ts: int, entry_price: float, horizon_sec: int) -> float | None:
    if entry_price <= 0:
        return None
    exit_price = _price_near(db, symbol, entry_ts + horizon_sec, window=3 * 86400)
    if exit_price is None or exit_price <= 0:
        return None
    raw = (exit_price - entry_price) / entry_price * 100.0
    return raw


def _signed_return(signal: str, ret_pct: float) -> float:
    if signal == "SELL":
        return -ret_pct
    if signal == "BUY":
        return ret_pct
    return 0.0


def _min_label_age_sec() -> int:
    """Intraday: label after 5m when session active; else 15m."""
    try:
        from ..strategies.market_session import is_nse_open

        return _H5M_SEC if is_nse_open() else _H15_SEC
    except Exception:
        return _H15_SEC


def label_strategy_signals(db: DB) -> dict[str, int]:
    """Label strategy_ledger + shadow_trades with forward 5m/15m/1d returns."""
    now = int(time.time())
    min_age = _min_label_age_sec()
    labeled = 0
    rows = db._conn.execute(
        """
        SELECT ts, strategy_id, symbol, signal, confidence, price, executed
        FROM strategy_ledger
        WHERE ts < ? AND ts NOT IN (SELECT ledger_ts FROM strategy_signal_outcomes)
        ORDER BY ts ASC LIMIT 500
        """,
        (now - min_age,),
    ).fetchall()
    shadow = db._conn.execute(
        """
        SELECT ts, strategy_id, symbol, action AS signal, confidence, price, 0 AS executed
        FROM shadow_trades
        WHERE ts < ? AND ts NOT IN (SELECT ledger_ts FROM strategy_signal_outcomes)
        ORDER BY ts ASC LIMIT 200
        """,
        (now - min_age,),
    ).fetchall()
    all_rows = list(rows) + list(shadow)
    with db.tx() as conn:
        for r in all_rows:
            ts = int(r["ts"])
            sym = str(r["symbol"] or "")
            price = float(r["price"] or 0)
            if not sym or price <= 0:
                continue
            ret_5m = _forward_return_pct(db, sym, ts, price, _H5M_SEC) if now >= ts + _H5M_SEC else None
            ret_15m = _forward_return_pct(db, sym, ts, price, _H15_SEC) if now >= ts + _H15_SEC else None
            if ret_15m is None and min_age == _H5M_SEC and ret_5m is not None:
                ret_15m = ret_5m
            ret_1d = _forward_return_pct(db, sym, ts, price, _H1D_SEC) if now >= ts + _H1D_SEC else None
            if ret_15m is None and ret_1d is None:
                continue
            conn.execute(
                """
                INSERT INTO strategy_signal_outcomes(
                  ledger_ts, strategy_id, symbol, signal, confidence, executed,
                  entry_price, ret_15m, ret_1d, labeled_ts
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ledger_ts) DO UPDATE SET
                  ret_15m=COALESCE(excluded.ret_15m, ret_15m),
                  ret_1d=COALESCE(excluded.ret_1d, ret_1d),
                  labeled_ts=excluded.labeled_ts
                """,
                (
                    ts,
                    str(r["strategy_id"]),
                    sym,
                    str(r["signal"]),
                    float(r["confidence"] or 0),
                    int(r["executed"] or 0),
                    price,
                    ret_15m,
                    ret_1d,
                    now,
                ),
            )
            labeled += 1
    logger.info("strategy_signals_labeled", extra={"count": labeled})
    return {"labeled": labeled}


def promote_discovery_rules(db: DB, *, min_win_rate: float = 0.54, limit: int = 5) -> list[dict[str, Any]]:
    """Promote mined rules when binomial edge + risk-adjusted fitness are significant."""
    from ..agent.strategy_stats import binomial_edge_p_value
    from ..risk.risk_metrics import fitness_from_returns

    rows = db._conn.execute(
        """
        SELECT rule_id, symbol, conditions, win_rate, avg_return, sample_count
        FROM strategy_discovery
        WHERE promoted=0 AND avg_return > 0 AND sample_count >= 20
        ORDER BY win_rate * avg_return DESC
        LIMIT ?
        """,
        (limit * 3,),
    ).fetchall()
    promoted_specs: list[dict[str, Any]] = []
    existing_row = db._conn.execute(
        "SELECT v FROM settings WHERE k=?", (KEY_LEARNED_CUSTOM,)
    ).fetchone()
    existing: list[dict] = []
    if existing_row:
        try:
            existing = json.loads(existing_row["v"])
        except json.JSONDecodeError:
            existing = []
    existing_ids = {str(x.get("id")) for x in existing}

    for r in rows:
        wins = int(round(float(r["win_rate"]) * int(r["sample_count"])))
        n = int(r["sample_count"])
        if float(r["win_rate"]) < min_win_rate:
            continue
        if binomial_edge_p_value(wins, n) > 0.05:
            continue
        proxy_rets = [float(r["avg_return"]) if float(r["win_rate"]) >= 0.5 else -abs(float(r["avg_return"]))] * min(n, 30)
        fit = fitness_from_returns(proxy_rets)
        if fit.composite <= 0 or fit.sortino < float(os.getenv("LIFECYCLE_MIN_SORTINO", "0.15")):
            continue
        if len(promoted_specs) >= limit:
            break
        try:
            rule = json.loads(r["conditions"])
        except json.JSONDecodeError:
            continue
        field = str(rule.get("field", ""))
        if not field:
            continue
        op = str(rule.get("op", "gt"))
        th = float(rule.get("threshold", 0))
        cond_key = f"{field}_gt" if op == "gt" else f"{field}_lt"
        rid = f"learned_{r['rule_id']}"
        if rid in existing_ids:
            continue
        spec = {
            "id": rid,
            "listens": ["BAR_CLOSE_5M"],
            "conditions": {cond_key: th},
            "action": "BUY",
            "rail": "MIS",
            "confidence": round(min(0.78, 0.52 + float(r["win_rate"]) * 0.25), 3),
            "reason": f"discovered_{rule.get('source', 'mined')}",
            "source": rule.get("source"),
            "win_rate": float(r["win_rate"]),
        }
        promoted_specs.append(spec)
        existing.append(spec)
        with db.tx() as conn:
            conn.execute(
                "UPDATE strategy_discovery SET promoted=1 WHERE rule_id=?",
                (r["rule_id"],),
            )

    if promoted_specs:
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (KEY_LEARNED_CUSTOM, json.dumps(existing[-30:])),
            )
        logger.info("discovery_rules_promoted", extra={"count": len(promoted_specs)})
    return promoted_specs


def learn_unified_strategy_weights(db: DB) -> dict[str, float]:
    """Merge signal outcomes + realized PnL + discovery + institutional into per-strategy multipliers."""
    weights: dict[str, float] = {}
    counts: dict[str, int] = {}

    outcome_rows = db._conn.execute(
        """
        SELECT strategy_id, signal, ret_15m, ret_1d, executed
        FROM strategy_signal_outcomes
        WHERE ret_15m IS NOT NULL
        """
    ).fetchall()
    buckets: dict[str, list[float]] = {}
    for r in outcome_rows:
        sid = str(r["strategy_id"])
        ret = _signed_return(str(r["signal"]), float(r["ret_15m"]))
        buckets.setdefault(sid, []).append(ret)

    for sid, rets in buckets.items():
        if len(rets) < _MIN_SAMPLES:
            continue
        from ..risk.risk_metrics import fitness_from_returns

        fit = fitness_from_returns(rets)
        edge = math.tanh(fit.composite / 2.0) * 0.2
        weights[sid] = round(max(0.7, min(1.35, 1.0 + edge)), 4)
        counts[sid] = len(rets)

    pnl_rows = db._conn.execute(
        "SELECT strategy_id, realized_pnl, trade_count FROM strategy_pnl WHERE trade_count > 0"
    ).fetchall()
    for r in pnl_rows:
        sid = str(r["strategy_id"])
        pnl = float(r["realized_pnl"] or 0)
        n = max(1, int(r["trade_count"] or 1))
        avg_pnl = pnl / n
        edge = math.tanh(avg_pnl / 200.0) * 0.12
        mult = round(max(0.75, min(1.3, 1.0 + edge)), 4)
        if sid in weights:
            weights[sid] = round((weights[sid] + mult) / 2, 4)
        else:
            weights[sid] = mult
        counts[sid] = counts.get(sid, 0) + n

    inst = load_institutional_weights(db).get("strategies") or {}
    for sid, mult in inst.items():
        if sid in weights:
            weights[sid] = round(weights[sid] * float(mult), 4)
        else:
            weights[sid] = float(mult)

    payload = {
        "strategies": weights,
        "sample_counts": counts,
        "outcome_samples": len(outcome_rows),
        "institutional_merged": len(inst),
        "ts": int(time.time()),
    }
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_STRATEGY_WEIGHTS, json.dumps(payload)),
        )
    logger.info(
        "unified_strategy_weights",
        extra={"strategies": len(weights), "outcomes": len(outcome_rows)},
    )
    return weights


def load_strategy_learn_weights(db: DB) -> dict[str, Any]:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_STRATEGY_WEIGHTS,)).fetchone()
    if not row:
        return {"strategies": {}, "sample_counts": {}}
    try:
        return json.loads(row["v"])
    except json.JSONDecodeError:
        return {"strategies": {}, "sample_counts": {}}


def strategy_weight_multiplier(weights: dict[str, Any], strategy_id: str) -> float:
    return float((weights.get("strategies") or {}).get(strategy_id, 1.0))


def load_learned_custom_strategies(db: DB) -> list[CustomRuleStrategy]:
    """Runtime-load agent-discovered rules promoted from bar_log mining."""
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_LEARNED_CUSTOM,)).fetchone()
    if not row:
        return []
    try:
        specs_raw = json.loads(row["v"])
    except json.JSONDecodeError:
        return []
    _event_map = {
        "BAR_CLOSE_5M": EventType.BAR_CLOSE_5M,
        "TICK": EventType.TICK,
        "SESSION_OPEN": EventType.SESSION_OPEN,
    }
    out: list[CustomRuleStrategy] = []
    for raw in specs_raw:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        listens = set()
        for name in raw.get("listens", ["BAR_CLOSE_5M"]):
            ev = _event_map.get(str(name).upper())
            if ev:
                listens.add(ev)
        if not listens:
            continue
        spec = CustomRuleSpec(
            id=str(raw["id"]),
            listens=listens,
            conditions={k: float(v) for k, v in (raw.get("conditions") or {}).items()},
            action=str(raw.get("action", "BUY")).upper(),
            rail=str(raw.get("rail", "MIS")).upper(),
            confidence=float(raw.get("confidence", 0.65)),
            reason=str(raw.get("reason", "learned_rule")),
        )
        out.append(CustomRuleStrategy(spec))
    return out


def seed_rl_from_strategy_signals(db: DB) -> dict[str, int]:
    """RL transitions from labeled strategy signals — learns from every fired signal."""
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (KEY_RL_STRATEGY_SEED_TS,)).fetchone()
    since = int(json.loads(row["v"])) if row else 0
    rows = db._conn.execute(
        """
        SELECT * FROM strategy_signal_outcomes
        WHERE labeled_ts > ? AND ret_15m IS NOT NULL
        ORDER BY labeled_ts ASC LIMIT 300
        """,
        (since,),
    ).fetchall()
    if not rows:
        return {"pushed": 0}

    buffer = RLBuffer(db)
    pushed = 0
    max_ts = since
    for r in rows:
        signal = str(r["signal"])
        ret = _signed_return(signal, float(r["ret_15m"]))
        reward = max(-1.0, min(1.0, ret / 2.0))
        conf = float(r["confidence"] or 0.5)
        state = encode_state_from_dict(
            {"regime": "NEUTRAL", "fii_net_cr": 0, "gift_nifty_change_pct": 0, "india_vix": 16},
            score=reward,
            confidence=conf,
            has_symbol=True,
        )
        action = index_action(1 if signal == "BUY" else (2 if signal == "SELL" else 0))
        next_state = encode_state_from_dict({"regime": "NEUTRAL"}, score=reward, confidence=conf * 0.9)
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
            (KEY_RL_STRATEGY_SEED_TS, json.dumps(max_ts)),
        )
    logger.info("strategy_rl_seeded", extra={"pushed": pushed})
    return {"pushed": pushed}


def refresh_all_learning(db: DB, ctx: Any) -> dict[str, Any]:
    """Master learning pass — corporate + signals + discovery + weights + RL."""
    label_sig = label_strategy_signals(db)
    label_corp = label_pending_events(db)
    from ..intelligence.strategy_correlation import refresh_disabled_strategies

    disabled = refresh_disabled_strategies(db)
    from ..agent.strategy_lifecycle import evaluate_lifecycle_transitions

    lifecycle = evaluate_lifecycle_transitions(db)
    promoted = promote_discovery_rules(db)
    strat_weights = learn_unified_strategy_weights(db)
    inst_weights = learn_institutional_weights(db)
    loaded = load_strategy_learn_weights(db)
    inst_loaded = load_institutional_weights(db)
    if hasattr(ctx, "strategy_learn_weights"):
        ctx.strategy_learn_weights = loaded
        ctx.institutional_weights = inst_loaded
    rl_inst = seed_rl_transitions_from_outcomes(db)
    rl_strat = seed_rl_from_strategy_signals(db)
    return {
        "signals_labeled": label_sig,
        "corporate_labeled": label_corp,
        "promoted_rules": len(promoted),
        "strategy_weights": len(strat_weights),
        "institutional_strategies": len(inst_weights),
        "rl_seed": {"institutional": rl_inst, "strategy": rl_strat},
        "disabled_strategies": len(disabled),
        "lifecycle_transitions": len([x for x in lifecycle if x.get("changed")]),
        "ts": int(time.time()),
    }

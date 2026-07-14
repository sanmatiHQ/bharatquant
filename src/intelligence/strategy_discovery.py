"""Mine bar_log for rule candidates — promote winners to custom_strategies."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..db.database import DB
from .strategy_catalog import DISCOVERY_RULES

logger = logging.getLogger("bharatquant.strategy_discovery")


def _rsi_from_closes(closes: list[float], idx: int, period: int = 14) -> float:
    if idx < period:
        return 50.0
    gains = 0.0
    losses = 0.0
    for j in range(idx - period + 1, idx + 1):
        delta = closes[j] - closes[j - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = (gains / period) / (losses / period)
    return 100.0 - (100.0 / (1.0 + rs))


def _bar_features_at(
    bars: list,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    vols: list[float],
    vol_avg: float,
    idx: int,
) -> dict[str, float]:
    c0 = closes[idx]
    r3m = (c0 - closes[idx - 3]) / closes[idx - 3] if idx >= 3 and closes[idx - 3] else 0.0
    hi = highs[idx]
    lo = lows[idx]
    rng = max(hi - lo, 0.0)
    ibs = (c0 - lo) / rng if rng > 0 else 0.5
    tail = closes[max(0, idx - 19) : idx + 1]
    z_score = 0.0
    if len(tail) >= 5:
        m = sum(tail) / len(tail)
        var = sum((x - m) ** 2 for x in tail) / len(tail)
        sd = var**0.5
        z_score = (c0 - m) / sd if sd > 0 else 0.0
    ranges = [max(highs[j] - lows[j], 0.0) for j in range(max(0, idx - 6), idx + 1)]
    nr7 = 1.0 if ranges and ranges[-1] <= min(ranges) * 1.001 else 0.0
    ema9 = sum(closes[max(0, idx - 8) : idx + 1]) / min(9, idx + 1)
    ema21 = sum(closes[max(0, idx - 20) : idx + 1]) / min(21, idx + 1)
    high_20 = max(highs[max(0, idx - 19) : idx + 1]) if idx >= 1 else hi
    donchian_brk = 1.0 if c0 > high_20 * 0.999 else 0.0
    near_high_20 = 1.0 if high_20 > 0 and c0 >= high_20 * 0.995 else 0.0
    lower_high_streak = 0.0
    if idx >= 2 and highs[idx] < highs[idx - 1]:
        streak = 1
        for j in range(idx - 1, max(0, idx - 5), -1):
            if highs[j] < highs[j - 1]:
                streak += 1
            else:
                break
        lower_high_streak = float(streak)
    vol_ratio = vols[idx] / vol_avg if vol_avg else 1.0
    return {
        "r3m": r3m,
        "rsi": _rsi_from_closes(closes, idx),
        "vol_ratio": vol_ratio,
        "ibs": ibs,
        "z_score": z_score,
        "nr7": nr7,
        "ema_cross_up": 1.0 if ema9 > ema21 else 0.0,
        "donchian_brk": donchian_brk,
        "near_high_20": near_high_20,
        "lower_high_streak": lower_high_streak,
    }


def _forward_return(closes: list[float], idx: int, horizon: int = 3) -> float | None:
    if idx + horizon >= len(closes):
        return None
    c0 = closes[idx]
    c1 = closes[idx + horizon]
    if c0 <= 0:
        return None
    return (c1 - c0) / c0


def forward_returns_for_discovery_rule(
    db: DB,
    symbol: str,
    rule: dict[str, Any],
    *,
    lookback_days: int = 14,
    min_samples: int = 20,
) -> list[float]:
    """Recompute actual per-hit forward returns for one mined rule (not repeated means)."""
    cutoff = int(time.time()) - lookback_days * 86400
    rows = db._conn.execute(
        """
        SELECT ts, open, high, low, close, volume FROM bar_log
        WHERE symbol=? AND interval='5m' AND ts >= ?
        ORDER BY ts
        """,
        (symbol, cutoff),
    ).fetchall()
    if len(rows) < 40:
        return []
    bars = list(rows)
    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    vols = [float(b["volume"] or 0) for b in bars]
    vol_avg = sum(vols) / len(vols) if vols else 1.0
    field = str(rule.get("field", ""))
    op = str(rule.get("op", "gt"))
    th = float(rule.get("threshold", 0))
    returns: list[float] = []
    for i in range(20, len(bars) - 4):
        feats = _bar_features_at(bars, closes, highs, lows, vols, vol_avg, i)
        val = feats.get(field, 0)
        ok = val > th if op == "gt" else val < th
        if not ok:
            continue
        fr = _forward_return(closes, i, 3)
        if fr is None:
            continue
        returns.append(fr)
    return returns if len(returns) >= min_samples else []


def mine_bar_log(db: DB, lookback_days: int = 14, min_samples: int = 20) -> list[dict[str, Any]]:
    """Scan bar_log 5m bars; score simple rules by forward 15m return."""
    cutoff = int(time.time()) - lookback_days * 86400
    rows = db._conn.execute(
        """
        SELECT ts, symbol, open, high, low, close, volume FROM bar_log
        WHERE interval='5m' AND ts >= ?
        ORDER BY symbol, ts
        """,
        (cutoff,),
    ).fetchall()
    by_sym: dict[str, list] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)

    discoveries: list[dict[str, Any]] = []
    for sym, bars in by_sym.items():
        if len(bars) < 40:
            continue
        closes = [float(b["close"]) for b in bars]
        highs = [float(b["high"]) for b in bars]
        lows = [float(b["low"]) for b in bars]
        vols = [float(b["volume"] or 0) for b in bars]
        vol_avg = sum(vols) / len(vols) if vols else 1.0

        for rule in DISCOVERY_RULES:
            hits = 0
            wins = 0
            ret_sum = 0.0
            for i in range(20, len(bars) - 4):
                feats = _bar_features_at(bars, closes, highs, lows, vols, vol_avg, i)
                val = feats.get(rule["field"], 0)
                ok = val > rule["threshold"] if rule["op"] == "gt" else val < rule["threshold"]
                if not ok:
                    continue
                fr = _forward_return(closes, i, 3)
                if fr is None:
                    continue
                hits += 1
                ret_sum += fr
                if fr > 0:
                    wins += 1
            if hits < min_samples:
                continue
            win_rate = wins / hits
            avg_ret = ret_sum / hits
            if win_rate < 0.52 or avg_ret <= 0:
                continue
            discoveries.append({
                "rule_id": f"{rule['rule_id']}_{sym}",
                "symbol": sym,
                "conditions": json.dumps({**rule, "source": rule.get("source", "mined")}),
                "win_rate": round(win_rate, 3),
                "avg_return": round(avg_ret * 100, 3),
                "sample_count": hits,
            })
    discoveries.sort(key=lambda x: x["win_rate"] * x["avg_return"], reverse=True)
    return discoveries[:15]


def persist_discoveries(db: DB, items: list[dict[str, Any]]) -> int:
    ts = int(time.time())
    n = 0
    with db.tx() as conn:
        for d in items:
            conn.execute(
                """
                INSERT INTO strategy_discovery(rule_id, symbol, conditions, win_rate, avg_return, sample_count, discovered_ts)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    d["rule_id"],
                    d.get("symbol"),
                    d["conditions"],
                    d["win_rate"],
                    d["avg_return"],
                    d["sample_count"],
                    ts,
                ),
            )
            n += 1
    return n


async def discovery_loop(db: DB, interval_sec: float = 3600.0) -> None:
    import asyncio

    while True:
        try:
            found = mine_bar_log(db)
            if found:
                persist_discoveries(db, found)
                from .strategy_learning import promote_discovery_rules, learn_unified_strategy_weights

                promote_discovery_rules(db)
                learn_unified_strategy_weights(db)
                logger.info("strategy_discovery", extra={"count": len(found)})
        except Exception:
            logger.exception("strategy_discovery_error")
        await asyncio.sleep(interval_sec)

"""Detect redundant strategies from historical signal timing correlation."""
from __future__ import annotations

import json
import logging
import os

from ..db.database import DB

logger = logging.getLogger("bharatquant.strategy_correlation")

_CORR_THRESH = float(os.getenv("STRATEGY_CORR_DISABLE_THRESH", "0.7"))
_LOOKBACK_SEC = int(os.getenv("STRATEGY_CORR_LOOKBACK_DAYS", "30")) * 86400
_BUCKET = 300


def _signal_buckets(db: DB, strategy_id: str, since_ts: int) -> dict[int, int]:
    buckets: dict[int, int] = {}
    rows = db._conn.execute(
        """
        SELECT ts, signal FROM strategy_ledger
        WHERE strategy_id=? AND ts >= ? AND signal IN ('BUY','SELL')
        """,
        (strategy_id, since_ts),
    ).fetchall()
    for r in rows:
        b = int(r["ts"]) // _BUCKET
        sign = 1 if r["signal"] == "BUY" else -1
        buckets[b] = sign
    return buckets


def pairwise_correlation(a: dict[int, int], b: dict[int, int]) -> float | None:
    keys = sorted(set(a) & set(b))
    if len(keys) < 20:
        return None
    va = [float(a[k]) for k in keys]
    vb = [float(b[k]) for k in keys]
    mean_a = sum(va) / len(va)
    mean_b = sum(vb) / len(vb)
    cov = sum((va[i] - mean_a) * (vb[i] - mean_b) for i in range(len(va))) / len(va)
    var_a = sum((x - mean_a) ** 2 for x in va) / len(va)
    var_b = sum((x - mean_b) ** 2 for x in vb) / len(vb)
    if var_a <= 1e-9 or var_b <= 1e-9:
        return None
    return cov / (var_a**0.5 * var_b**0.5)


def find_redundant_pairs(db: DB) -> list[tuple[str, str, float]]:
    since = int(__import__("time").time()) - _LOOKBACK_SEC
    sids = [
        str(r["strategy_id"])
        for r in db._conn.execute(
            """
            SELECT DISTINCT strategy_id FROM strategy_ledger
            WHERE ts >= ? AND strategy_id IS NOT NULL
            """,
            (since,),
        ).fetchall()
    ]
    series = {sid: _signal_buckets(db, sid, since) for sid in sids}
    pairs: list[tuple[str, str, float]] = []
    for i, s1 in enumerate(sids):
        for s2 in sids[i + 1 :]:
            corr = pairwise_correlation(series[s1], series[s2])
            if corr is not None and abs(corr) >= _CORR_THRESH:
                pairs.append((s1, s2, corr))
    return pairs


def refresh_disabled_strategies(db: DB) -> list[str]:
    """Disable lower-expectancy member of each highly correlated pair."""
    from ..agent.strategy_stats import strategy_performance, strategy_fitness

    pairs = find_redundant_pairs(db)
    disabled: set[str] = set()
    for s1, s2, corr in pairs:
        p1 = strategy_performance(db, s1)
        p2 = strategy_performance(db, s2)
        f1 = strategy_fitness(db, s1)
        f2 = strategy_fitness(db, s2)
        score1 = f1.composite if f1.n >= 10 else p1.win_rate * p1.expected_move_pct
        score2 = f2.composite if f2.n >= 10 else p2.win_rate * p2.expected_move_pct
        loser = s2 if score1 >= score2 else s1
        disabled.add(loser)
        logger.info("strategy_corr_disable", extra={"pair": (s1, s2), "corr": round(corr, 3), "disabled": loser})
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("disabled_strategies", json.dumps(sorted(disabled))),
        )
    return sorted(disabled)


def is_strategy_disabled(db: DB, strategy_id: str) -> bool:
    row = db._conn.execute("SELECT v FROM settings WHERE k='disabled_strategies'").fetchone()
    if not row:
        return False
    try:
        disabled = set(json.loads(row["v"]))
    except json.JSONDecodeError:
        return False
    return strategy_id in disabled

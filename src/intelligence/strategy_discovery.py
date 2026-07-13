"""Mine bar_log for rule candidates — promote winners to custom_strategies."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..db.database import DB

logger = logging.getLogger("bharatquant.strategy_discovery")

_RULES = (
    {"rule_id": "mom_r3m_pos", "field": "r3m", "op": "gt", "threshold": 0.006},
    {"rule_id": "mom_rsi_os", "field": "rsi", "op": "lt", "threshold": 35},
    {"rule_id": "vol_spike", "field": "vol_ratio", "op": "gt", "threshold": 2.0},
)


def _forward_return(closes: list[float], idx: int, horizon: int = 3) -> float | None:
    if idx + horizon >= len(closes):
        return None
    c0 = closes[idx]
    c1 = closes[idx + horizon]
    if c0 <= 0:
        return None
    return (c1 - c0) / c0


def mine_bar_log(db: DB, lookback_days: int = 14, min_samples: int = 20) -> list[dict[str, Any]]:
    """Scan bar_log 5m bars; score simple rules by forward 15m return."""
    cutoff = int(time.time()) - lookback_days * 86400
    rows = db._conn.execute(
        """
        SELECT ts, symbol, close, volume FROM bar_log
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
        vols = [float(b["volume"] or 0) for b in bars]
        vol_avg = sum(vols) / len(vols) if vols else 1.0

        for rule in _RULES:
            hits = 0
            wins = 0
            ret_sum = 0.0
            for i in range(20, len(bars) - 4):
                r3m = (closes[i] - closes[i - 3]) / closes[i - 3] if closes[i - 3] else 0
                rsi_proxy = 50.0  # simplified without full RSI on history
                vol_ratio = vols[i] / vol_avg if vol_avg else 1.0
                val = {"r3m": r3m, "rsi": rsi_proxy, "vol_ratio": vol_ratio}.get(rule["field"], 0)
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
                "conditions": json.dumps(rule),
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
                logger.info("strategy_discovery", extra={"count": len(found)})
        except Exception:
            logger.exception("strategy_discovery_error")
        await asyncio.sleep(interval_sec)

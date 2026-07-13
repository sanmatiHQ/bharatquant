"""Thompson-style bandit weights from strategy_ledger — no LLM."""
from __future__ import annotations

import json
import math
from typing import Dict

from ..intelligence.strategy_learning import load_strategy_learn_weights


class StrategyBandit:
    def __init__(self, db: DB) -> None:
        self.db = db

    def _institutional_strategy_weights(self) -> Dict[str, float]:
        row = self.db._conn.execute(
            "SELECT v FROM settings WHERE k=?", ("institutional_learn_weights",)
        ).fetchone()
        if not row:
            return {}
        try:
            data = json.loads(row["v"])
            return {str(k): float(v) for k, v in (data.get("strategies") or {}).items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}

    def update_weights(self) -> Dict[str, float]:
        cur = self.db._conn.execute(
            """
            SELECT strategy_id,
                   SUM(CASE WHEN executed=1 THEN confidence ELSE 0 END) as hits,
                   COUNT(*) as n
            FROM strategy_ledger
            WHERE ts > strftime('%s','now') - 30*86400
            GROUP BY strategy_id
            """
        )
        weights: Dict[str, float] = {}
        for row in cur.fetchall():
            n = max(1, int(row["n"]))
            hits = float(row["hits"] or 0)
            weights[row["strategy_id"]] = max(0.1, hits / n + 1.0 / math.sqrt(n))
        inst = self._institutional_strategy_weights()
        for sid, mult in inst.items():
            base = weights.get(sid, 1.0)
            weights[sid] = max(0.1, base * mult)
        unified = load_strategy_learn_weights(self.db).get("strategies") or {}
        for sid, mult in unified.items():
            base = weights.get(sid, 1.0)
            weights[sid] = max(0.1, base * float(mult))
        return weights

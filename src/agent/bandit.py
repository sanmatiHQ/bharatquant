"""Thompson-style bandit weights from strategy_ledger — no LLM."""
from __future__ import annotations

import math
from typing import Dict

from ..db.database import DB


class StrategyBandit:
    def __init__(self, db: DB) -> None:
        self.db = db

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
        return weights

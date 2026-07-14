"""Thompson sampling bandit — outcome-based weights with diversity cap."""
from __future__ import annotations

import json
import os
import random
from typing import Dict

from ..db.database import DB
from ..agent.strategy_stats import thompson_win_loss_counts
from ..intelligence.strategy_learning import load_strategy_learn_weights


def _apply_diversity_cap(weights: Dict[str, float]) -> Dict[str, float]:
    """Never let one strategy dominate — cap max weight and redistribute."""
    max_w = float(os.getenv("BANDIT_MAX_WEIGHT", "0.40"))
    floor = float(os.getenv("BANDIT_MIN_WEIGHT", "0.05"))
    if not weights:
        return weights
    capped = {k: min(v, max_w) for k, v in weights.items()}
    total = sum(capped.values())
    if total <= 0:
        return {k: floor for k in weights}
    scale = len(weights) * 0.5 / total
    out = {k: max(floor, min(max_w, v * scale)) for k, v in capped.items()}
    return out


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
        sids = [
            str(r["strategy_id"])
            for r in self.db._conn.execute(
                "SELECT DISTINCT strategy_id FROM strategy_ledger WHERE strategy_id IS NOT NULL"
            ).fetchall()
        ]
        weights: Dict[str, float] = {}
        for sid in sids:
            alpha, beta = thompson_win_loss_counts(self.db, sid)
            sample = random.betavariate(max(alpha, 0.1), max(beta, 0.1))
            weights[sid] = max(0.05, min(1.5, sample * 2.0))
        inst = self._institutional_strategy_weights()
        for sid, mult in inst.items():
            weights[sid] = max(0.05, weights.get(sid, 1.0) * mult)
        unified = load_strategy_learn_weights(self.db).get("strategies") or {}
        for sid, mult in unified.items():
            weights[sid] = max(0.05, weights.get(sid, 1.0) * float(mult))
        return _apply_diversity_cap(weights)

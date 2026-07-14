"""
Per-strategy performance stats — single source for Kelly, cost-edge, bandit, promotion gates.
Derived from strategy_signal_outcomes + strategy_pnl (no hardcoded win rates).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

from ..db.database import DB

_MIN_CLOSED = int(os.getenv("STRATEGY_STATS_MIN_SAMPLES", "10"))
_PRIOR_ALPHA = float(os.getenv("KELLY_PRIOR_ALPHA", "3"))
_PRIOR_BETA = float(os.getenv("KELLY_PRIOR_BETA", "3"))
_LOOKBACK = int(os.getenv("STRATEGY_STATS_LOOKBACK", "60"))


@dataclass(frozen=True)
class StrategyPerformance:
    strategy_id: str
    sample_count: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    expected_move_pct: float
    wins: int
    losses: int

    @property
    def has_edge_data(self) -> bool:
        return self.sample_count >= _MIN_CLOSED


def _signed_returns(rows: list) -> list[float]:
    out: list[float] = []
    for r in rows:
        ret = float(r["ret_15m"])
        sig = str(r["signal"] or "BUY")
        if sig == "SELL":
            out.append(-ret)
        elif sig == "BUY":
            out.append(ret)
    return out


def _fetch_outcome_rows(db: DB, strategy_id: str, *, executed_only: bool) -> list:
    sql = """
        SELECT o.ret_15m, l.signal
        FROM strategy_signal_outcomes o
        JOIN strategy_ledger l ON l.ts = o.ledger_ts
        WHERE l.strategy_id = ? AND o.ret_15m IS NOT NULL
    """
    if executed_only:
        sql += " AND l.executed = 1"
    sql += " ORDER BY o.ledger_ts DESC LIMIT ?"
    return list(db._conn.execute(sql, (strategy_id, _LOOKBACK)).fetchall())


def strategy_performance(db: DB, strategy_id: str) -> StrategyPerformance:
    """Bayesian-shrunk win rate + measured avg win/loss % and expected absolute move."""
    if not strategy_id:
        return StrategyPerformance("", 0, 0.5, 1.0, 1.0, 0.0, 0, 0)

    rows = _fetch_outcome_rows(db, strategy_id, executed_only=True)
    if len(rows) < _MIN_CLOSED:
        rows = _fetch_outcome_rows(db, strategy_id, executed_only=False)

    signed = _signed_returns(rows)
    if len(signed) < _MIN_CLOSED:
        row = db._conn.execute(
            "SELECT realized_pnl, trade_count FROM strategy_pnl WHERE strategy_id=? AND trade_count > 0",
            (strategy_id,),
        ).fetchone()
        if row and int(row["trade_count"] or 0) >= _MIN_CLOSED:
            n = int(row["trade_count"])
            avg_inr = float(row["realized_pnl"] or 0) / n
            wr = 0.5 + math.tanh(avg_inr / 400.0) * 0.1
            move = max(abs(avg_inr) / 50.0, 0.3)
            return StrategyPerformance(
                strategy_id, n, wr, move, move, move, max(0, int(wr * n)), max(0, n - int(wr * n))
            )
        return StrategyPerformance(strategy_id, len(signed), 0.5, 1.0, 1.0, 0.0, 0, 0)

    wins = [x for x in signed if x > 0]
    losses = [abs(x) for x in signed if x <= 0]
    raw_wr = len(wins) / len(signed)
    # Beta(_PRIOR_ALPHA, _PRIOR_BETA) prior blended with observed win rate
    win_rate = (_PRIOR_ALPHA + len(wins)) / (_PRIOR_ALPHA + _PRIOR_BETA + len(signed))
    avg_win = sum(wins) / len(wins) if wins else 0.3
    avg_loss = sum(losses) / len(losses) if losses else 0.3
    expected_move = sum(abs(x) for x in signed) / len(signed)
    return StrategyPerformance(
        strategy_id=strategy_id,
        sample_count=len(signed),
        win_rate=win_rate,
        avg_win_pct=max(avg_win, 0.05),
        avg_loss_pct=max(avg_loss, 0.05),
        expected_move_pct=max(expected_move, 0.05),
        wins=len(wins),
        losses=len(losses),
    )


def kelly_inputs_for_strategy(db: DB, strategy_id: str) -> tuple[float, float, float]:
    perf = strategy_performance(db, strategy_id)
    if not perf.has_edge_data:
        return 0.5, 1.0, 1.0
    return perf.win_rate, perf.avg_win_pct, perf.avg_loss_pct


def expected_move_pct_for_strategy(db: DB, strategy_id: str, confidence: float, corp_mult: float = 1.0) -> float:
    perf = strategy_performance(db, strategy_id)
    base = perf.expected_move_pct if perf.has_edge_data else 0.0
    if base <= 0:
        return 0.0
    return base * max(0.0, min(1.0, confidence)) * corp_mult


def thompson_win_loss_counts(db: DB, strategy_id: str) -> tuple[int, int]:
    perf = strategy_performance(db, strategy_id)
    return perf.wins + int(_PRIOR_ALPHA), perf.losses + int(_PRIOR_BETA)


def binomial_edge_p_value(wins: int, n: int, null_p: float = 0.5) -> float:
    """One-sided p-value: P(X >= wins | Binomial(n, null_p))."""
    if n <= 0 or wins <= 0:
        return 1.0
    if n >= 100:
        # Normal approximation with continuity correction (stable for large n).
        mu = n * null_p
        sigma = math.sqrt(n * null_p * (1.0 - null_p))
        if sigma <= 0:
            return 0.0 if wins > mu else 1.0
        z = (wins - 0.5 - mu) / sigma
        return min(1.0, max(0.0, 0.5 * math.erfc(z / math.sqrt(2))))
    p = 0.0
    for k in range(wins, n + 1):
        p += math.comb(n, k) * (null_p**k) * ((1.0 - null_p) ** (n - k))
    return min(1.0, p)


def win_rate_variance(db: DB, strategy_id: str) -> float:
    """Variance of recent binary win indicators — high = noisy edge estimate."""
    rows = _fetch_outcome_rows(db, strategy_id, executed_only=True)
    if len(rows) < 5:
        rows = _fetch_outcome_rows(db, strategy_id, executed_only=False)
    signed = _signed_returns(rows)
    if len(signed) < 5:
        return 0.25
    indicators = [1.0 if x > 0 else 0.0 for x in signed[:20]]
    mean = sum(indicators) / len(indicators)
    return sum((x - mean) ** 2 for x in indicators) / len(indicators)


def strategy_return_series(db: DB, strategy_id: str) -> list[float]:
    rows = _fetch_outcome_rows(db, strategy_id, executed_only=False)
    return _signed_returns(rows)


def strategy_fitness(db: DB, strategy_id: str):
    from ..risk.risk_metrics import PERIODS_PER_YEAR_SIGNAL, fitness_from_returns

    return fitness_from_returns(strategy_return_series(db, strategy_id), periods_per_year=PERIODS_PER_YEAR_SIGNAL)

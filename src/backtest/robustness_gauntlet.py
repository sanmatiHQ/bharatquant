"""
Backtest robustness gauntlet for discovery-mined rules.

Concept borrowed from community forward-testing practice (independently repeated
across several unrelated builders): treat any auto-discovered rule as overfit
garbage until it survives being pushed on. Three pushes, each cheap to compute
from a rule's own realized forward-return series:

1. Parameter jitter — nudge the rule's threshold +/-10% and recompute. An edge
   that only exists at one exact threshold value is curve-fit to that value, not
   a real effect.
2. Doubled cost stress — subtract an extra round-trip's worth of real trading
   cost from every return. An edge that only survives at 1x assumed costs is
   fragile to any slippage/fee model error.
3. Best-trades removed — drop the single largest winning return and recompute.
   An edge that depends on one outlier trade isn't a repeatable edge.

This does not replace historical_screen's binomial-significance/Sortino floor —
it's an additional, independent stress pass specifically for rules mined by
strategy_discovery.py, the highest overfitting-risk source in the system.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..costs.cost_engine import CostEngine
from ..risk.risk_metrics import fitness_from_returns

_MIN_SORTINO = float(os.getenv("GAUNTLET_MIN_SORTINO", "0.0"))
_JITTER_PCT = float(os.getenv("GAUNTLET_JITTER_PCT", "0.10"))


@dataclass(frozen=True)
class GauntletResult:
    passed: bool
    reasons: list[str]
    base_sortino: float
    jitter_down_sortino: float
    jitter_up_sortino: float
    doubled_cost_sortino: float
    trimmed_best_sortino: float
    best_day_removed_sortino: float | None = None


def doubled_cost_returns(returns: list[float], *, price_hint: float = 100.0, qty_hint: int = 1) -> list[float]:
    """Subtract one extra round-trip's worth of real cost from every return."""
    if not returns:
        return []
    costs = CostEngine(slippage_bps=4)
    round_trip_pct = costs.round_trip_cost_inr(qty_hint, price_hint) / max(price_hint * qty_hint, 1.0)
    return [r - round_trip_pct for r in returns]


def trimmed_best_returns(returns: list[float], drop_frac: float = 0.05) -> list[float]:
    """Drop the largest `drop_frac` of returns (at least one), keep relative order."""
    if not returns:
        return []
    n_drop = max(1, int(len(returns) * drop_frac))
    ranked = sorted(range(len(returns)), key=lambda i: returns[i], reverse=True)
    drop_idx = set(ranked[:n_drop])
    return [r for i, r in enumerate(returns) if i not in drop_idx]


def remove_best_day_returns(ts_returns: list[tuple[int, float]]) -> list[float] | None:
    """
    Drop every trade that occurred on the single best calendar day (by summed
    return that day), not just the single best trade. A rule whose entire edge
    comes from one lucky session isn't a repeatable edge either — the single-
    trade check above can miss this when the best day's return is spread across
    several merely-good trades that individually look unremarkable.

    Returns None (meaning "not evaluable, don't fail this check") if all trades
    fall on a single calendar day — removing "the best day" would then remove
    every trade, which tests data coverage, not edge robustness.
    """
    if not ts_returns:
        return []
    day_totals: dict[int, float] = {}
    for ts, ret in ts_returns:
        day = ts // 86400
        day_totals[day] = day_totals.get(day, 0.0) + ret
    if len(day_totals) < 2:
        return None
    best_day = max(day_totals, key=lambda d: day_totals[d])
    return [ret for ts, ret in ts_returns if (ts // 86400) != best_day]


def jittered_returns_fn_signature() -> None:
    """No-op placeholder documenting that jitter is applied at the caller level
    (re-running forward_returns_for_discovery_rule at threshold*(1+/-pct)) since
    it requires re-scanning bar_log with a different threshold, not just
    reshaping an existing return list."""


def run_gauntlet(
    base_returns: list[float],
    jitter_down_returns: list[float],
    jitter_up_returns: list[float],
    *,
    price_hint: float = 100.0,
    qty_hint: int = 1,
    min_sortino: float | None = None,
    base_returns_with_ts: list[tuple[int, float]] | None = None,
) -> GauntletResult:
    """
    All three positional inputs are pre-computed forward-return series:
    - base_returns: at the rule's original threshold
    - jitter_down_returns / jitter_up_returns: at threshold*(1-pct) / threshold*(1+pct)
    Doubled-cost and best-trades-removed checks are derived from base_returns here.

    base_returns_with_ts is optional (ts, return) pairs for the best-day-removed
    check — a rule whose entire edge comes from one lucky session, spread across
    several individually-unremarkable trades, can pass the single-best-trade
    check while still not being a repeatable edge. Skipped gracefully (not a
    failure) when timestamps aren't available, same cold-start discipline used
    throughout this codebase.
    """
    floor = min_sortino if min_sortino is not None else _MIN_SORTINO
    reasons: list[str] = []

    base_fit = fitness_from_returns(base_returns, periods_per_year=252)
    down_fit = fitness_from_returns(jitter_down_returns, periods_per_year=252) if jitter_down_returns else None
    up_fit = fitness_from_returns(jitter_up_returns, periods_per_year=252) if jitter_up_returns else None
    doubled = doubled_cost_returns(base_returns, price_hint=price_hint, qty_hint=qty_hint)
    doubled_fit = fitness_from_returns(doubled, periods_per_year=252)
    trimmed = trimmed_best_returns(base_returns)
    trimmed_fit = fitness_from_returns(trimmed, periods_per_year=252)

    best_day_fit = None
    if base_returns_with_ts:
        day_trimmed = remove_best_day_returns(base_returns_with_ts)
        if day_trimmed is not None:
            best_day_fit = fitness_from_returns(day_trimmed, periods_per_year=252)

    if base_fit.sortino <= floor:
        reasons.append("base_sortino_below_floor")
    if down_fit is None or down_fit.sortino <= floor:
        reasons.append("fails_jitter_down")
    if up_fit is None or up_fit.sortino <= floor:
        reasons.append("fails_jitter_up")
    if doubled_fit.sortino <= floor:
        reasons.append("fails_doubled_cost_stress")
    if trimmed_fit.sortino <= floor:
        reasons.append("edge_depends_on_best_trades")
    if best_day_fit is not None and best_day_fit.sortino <= floor:
        reasons.append("edge_depends_on_best_day")

    return GauntletResult(
        passed=len(reasons) == 0,
        reasons=reasons,
        base_sortino=base_fit.sortino,
        jitter_down_sortino=down_fit.sortino if down_fit else 0.0,
        jitter_up_sortino=up_fit.sortino if up_fit else 0.0,
        doubled_cost_sortino=doubled_fit.sortino,
        trimmed_best_sortino=trimmed_fit.sortino,
        best_day_removed_sortino=best_day_fit.sortino if best_day_fit is not None else None,
    )


def jittered_thresholds(threshold: float, pct: float | None = None) -> tuple[float, float]:
    """Returns (threshold*(1-pct), threshold*(1+pct))."""
    p = pct if pct is not None else _JITTER_PCT
    return threshold * (1 - p), threshold * (1 + p)

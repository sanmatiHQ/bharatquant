"""Robustness gauntlet — parameter jitter, doubled-cost stress, best-trade removal.
Concept borrowed from independently-repeated community forward-testing practice:
assume any discovered rule is overfit until it survives being pushed on.
"""
from __future__ import annotations

import pytest

from src.backtest.robustness_gauntlet import (
    doubled_cost_returns,
    jittered_thresholds,
    run_gauntlet,
    trimmed_best_returns,
)


def test_jittered_thresholds_symmetric():
    lo, hi = jittered_thresholds(1.0, pct=0.10)
    assert lo == pytest.approx(0.9)
    assert hi == pytest.approx(1.1)


def test_doubled_cost_returns_subtracts_a_flat_amount():
    base = [0.02, 0.03, -0.01]
    out = doubled_cost_returns(base, price_hint=100.0, qty_hint=10)
    assert len(out) == 3
    # every return should be reduced by the same round-trip cost estimate
    diffs = [b - o for b, o in zip(base, out)]
    assert diffs[0] == pytest.approx(diffs[1])
    assert diffs[0] == pytest.approx(diffs[2])
    assert diffs[0] > 0  # cost always makes returns worse, never better


def test_trimmed_best_returns_drops_the_biggest_winners():
    rets = [0.01, 0.02, 0.50, -0.01, 0.015]  # 0.50 is a wild outlier
    out = trimmed_best_returns(rets, drop_frac=0.2)  # drop top 1 of 5
    assert 0.50 not in out
    assert len(out) == 4


def test_robust_edge_passes_full_gauntlet():
    # consistent, modest positive edge with realistic mixed win/loss variance
    # (not uniform gains, which would be an unrealistic zero-downside-variance
    # sample), >=20 samples per series so the n>=20 trust gate in risk_metrics
    # doesn't (correctly) refuse to trust a small sample.
    # ~4% average moves — comfortably clears the ~1% round-trip cost floor at
    # this trade size (Zerodha's flat ~Rs20 min commission dominates small
    # turnover), so this is genuinely testing "robust vs fragile," not "too
    # thin to survive any real cost at all."
    base = [0.05, 0.04, -0.02, 0.045, 0.035, -0.015, 0.052, 0.038, -0.022, 0.042] * 3
    jitter_down = [0.045, 0.036, -0.018, 0.04, 0.032, -0.013, 0.047, 0.034, -0.02, 0.038] * 3
    jitter_up = [0.047, 0.037, -0.018, 0.042, 0.033, -0.014, 0.049, 0.035, -0.021, 0.039] * 3
    result = run_gauntlet(base, jitter_down, jitter_up, price_hint=1000.0, qty_hint=5)
    assert result.passed, f"expected a robust edge to pass, got reasons: {result.reasons}"


def test_edge_that_vanishes_off_threshold_fails_jitter():
    # only "works" at the exact base threshold — nudge it either way and the
    # edge disappears (classic curve-fit signature)
    base = [0.02] * 30
    jitter_down = [-0.01, 0.005, -0.02, 0.01, -0.015] * 6  # no real edge here
    jitter_up = [-0.02, 0.01, -0.01, 0.005, -0.015] * 6
    result = run_gauntlet(base, jitter_down, jitter_up, price_hint=1000.0, qty_hint=5)
    assert not result.passed
    assert "fails_jitter_down" in result.reasons
    assert "fails_jitter_up" in result.reasons


def test_thin_edge_fails_doubled_cost_stress():
    # a real but tiny edge, smaller than one extra round-trip's cost
    tiny = [0.0006, 0.0005, 0.0007, 0.0004, 0.0006] * 10
    result = run_gauntlet(tiny, tiny, tiny, price_hint=1000.0, qty_hint=1)
    assert not result.passed
    assert "fails_doubled_cost_stress" in result.reasons


def test_outlier_dependent_edge_fails_trimmed_check():
    # 24 small consistent losses propped up entirely by ONE huge winning trade —
    # a single genuine outlier among >=20 samples, not a repeated pattern
    # (repeating the outlier would just create several outliers, defeating the
    # "drop only the single biggest winner" check this test is meant to exercise).
    base = [-0.01, -0.008, -0.012, -0.009, -0.011, -0.01, -0.009, -0.0095] * 3 + [2.5]
    result = run_gauntlet(base, base, base, price_hint=1000.0, qty_hint=1)
    assert not result.passed
    assert "edge_depends_on_best_trades" in result.reasons

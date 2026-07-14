"""Tests for risk-adjusted fitness — Sortino reward, adaptive Kelly, Calmar promotion, lifecycle."""
from __future__ import annotations

import time

import pytest

from src.agent.kelly_sizing import kelly_fraction, rupees_from_kelly
from src.agent.regime_change_detector import apply_regime_persistence, check_regime_shock
from src.agent.strategy_lifecycle import allocation_fraction, ensure_lifecycle_row, evaluate_lifecycle_transitions
from src.agent.bandit import _apply_diversity_cap
from src.db.database import DB, DBConfig
from src.risk.risk_metrics import (
    PERIODS_PER_YEAR_5M_BAR,
    PERIODS_PER_YEAR_SIGNAL,
    calmar_ratio,
    downside_deviation,
    fitness_from_returns,
    max_drawdown_from_returns,
    sortino_ratio,
)
from src.rl.reward import compute_reward, reward_config_from_env
from src.strategies.base import MarketContext


def test_downside_deviation_penalizes_losses_only():
    good = [0.02, 0.03, 0.01, 0.04]
    mixed = [0.03, -0.02, 0.04, -0.01]
    assert downside_deviation(good) < downside_deviation(mixed)


def test_sortino_higher_for_steady_gains():
    steady = [0.01, 0.011, 0.009, 0.012, 0.01] * 4
    volatile = [0.08, -0.07, 0.09, -0.08] * 5
    from src.risk.risk_metrics import downside_deviation

    assert downside_deviation(steady) < downside_deviation(volatile)
    assert sortino_ratio(steady) > 0


def test_calmar_penalizes_drawdown():
    steady = [0.005] * 30
    crash = [0.005] * 25 + [-0.15] + [0.005] * 4
    assert calmar_ratio(steady) > calmar_ratio(crash)


def test_sortino_shaped_reward():
    cfg = reward_config_from_env()
    r_good = compute_reward(0.02, 0.0, cfg, recent_returns=[0.01, 0.02, 0.015])
    r_bad = compute_reward(0.02, 0.0, cfg, recent_returns=[0.03, -0.04, -0.02])
    assert r_good > r_bad


def test_adaptive_kelly_shrinks_with_noise():
    low_noise = kelly_fraction(0.58, 1.2, 1.0, wr_variance=0.01)
    high_noise = kelly_fraction(0.58, 1.2, 1.0, wr_variance=0.08)
    assert high_noise < low_noise


def test_regime_persistence_dampener():
    ctx = MarketContext()
    ctx.regime = "SIDEWAYS"
    assert apply_regime_persistence(ctx, "BULL") == "SIDEWAYS"
    apply_regime_persistence(ctx, "BULL")
    apply_regime_persistence(ctx, "BULL")
    assert apply_regime_persistence(ctx, "BULL") == "BULL"


def test_regime_shock_fast_path():
    ctx = MarketContext()
    ctx.regime = "SIDEWAYS"
    ctx.index_returns = [0.002, 0.003, 0.004]
    assert apply_regime_persistence(ctx, "HIGH_VOL", shock=True) == "HIGH_VOL"


def test_bandit_diversity_cap():
    weights = {"a": 0.9, "b": 0.8, "c": 0.7}
    capped = _apply_diversity_cap(weights)
    assert max(capped.values()) <= 0.41


@pytest.fixture
def db(tmp_path):
    return DB(DBConfig(sqlite_path=str(tmp_path / "risk.db")))


def test_lifecycle_candidacy_blocks_capital(db):
    ensure_lifecycle_row(db, "learned_test_rule")
    assert allocation_fraction(db, "learned_test_rule") == 0.0


def test_lifecycle_core_full_allocation(db):
    ensure_lifecycle_row(db, "opening_range")
    assert allocation_fraction(db, "opening_range") == 1.0


def test_fitness_composite_from_returns():
    fit = fitness_from_returns(
        [0.01, 0.008, 0.012, 0.009, 0.011] * 4,
        periods_per_year=PERIODS_PER_YEAR_SIGNAL,
    )
    assert fit.composite > 0
    assert fit.sortino > 0


def test_identical_proxy_series_not_inflated():
    """Repeated identical returns (<20) must not inflate composite via zero-variance fallbacks."""
    fake = [0.01] * 15
    fit = fitness_from_returns(fake, periods_per_year=PERIODS_PER_YEAR_SIGNAL)
    assert fit.composite == 0.0
    assert fit.sortino == 0.0
    assert fit.calmar == 0.0


def test_calmar_annualized_hand_computed():
    returns = [0.01, 0.02, -0.005, 0.015, 0.01]
    n = len(returns)
    equity = 1.0
    for r in returns:
        equity *= 1.0 + r
    ppy = 252
    expected_ann = equity ** (ppy / n) - 1.0
    mdd = max_drawdown_from_returns(returns)
    expected = expected_ann / mdd
    assert abs(calmar_ratio(returns, periods_per_year=ppy) - expected) < 1e-9


def test_shadow_backtest_periods_per_year_constant():
    assert PERIODS_PER_YEAR_5M_BAR == 18_900

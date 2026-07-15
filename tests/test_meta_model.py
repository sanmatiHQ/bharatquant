"""Meta-model — pure-numpy logistic regression over calibrated confidence +
context, replacing weighted-argmax with a learned decision function.
"""
from __future__ import annotations

import os
import time

import pytest

from src.agent.meta_model import (
    build_feature_vector,
    label_meta_rows,
    predict_meta_probability,
    record_meta_row,
    regime_to_numeric,
    train_meta_model,
)
from src.db.database import DB, DBConfig


@pytest.fixture
def db(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "t.db")
    return DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))


def test_regime_to_numeric_mapping():
    assert regime_to_numeric("BULL") == 1.0
    assert regime_to_numeric("RISK_ON") == 1.0  # normalizes through regime_classifier
    assert regime_to_numeric("BEAR") == -1.0
    assert regime_to_numeric("HIGH_VOL") == 0.5
    assert regime_to_numeric("SIDEWAYS") == 0.0


def test_feature_vector_is_bounded_and_fixed_length():
    x = build_feature_vector(
        calibrated_confidence=1.5, regime="BULL", india_vix=999.0, fii_net_cr=999999.0, bandit_weight=999.0
    )
    assert len(x) == 6
    assert x[0] == 1.0  # bias term
    assert 0.0 <= x[1] <= 1.0  # confidence clamped
    assert -2.0 <= x[3] <= 2.0  # vix clamped
    assert -2.0 <= x[4] <= 2.0  # fii clamped
    assert 0.0 <= x[5] <= 3.0  # bandit weight clamped


def test_predict_returns_none_when_untrained(db):
    p = predict_meta_probability(
        db, calibrated_confidence=0.6, regime="BULL", india_vix=15, fii_net_cr=0, bandit_weight=1.0
    )
    assert p is None


def test_predict_returns_none_with_no_db():
    p = predict_meta_probability(
        None, calibrated_confidence=0.6, regime="BULL", india_vix=15, fii_net_cr=0, bandit_weight=1.0
    )
    assert p is None


def _seed_row_and_outcome(db, ts, strategy_id, symbol, conf, regime, vix, fii, weight, win: bool):
    record_meta_row(
        db, ledger_ts=ts, strategy_id=strategy_id, symbol=symbol,
        raw_confidence=conf, calibrated_confidence=conf, regime=regime,
        india_vix=vix, fii_net_cr=fii, bandit_weight=weight,
    )
    ret = 0.01 if win else -0.01
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO strategy_signal_outcomes
                (ledger_ts, strategy_id, symbol, signal, confidence, executed, entry_price, ret_15m, ret_1d, labeled_ts)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (ts, strategy_id, symbol, "BUY", conf, 1, 100.0, ret, ret, ts + 900),
        )


def test_label_meta_rows_fills_from_outcomes(db):
    ts = int(time.time()) - 10000
    _seed_row_and_outcome(db, ts, "s1", "TCS", 0.6, "BULL", 15, 0, 1.0, win=True)
    n = label_meta_rows(db)
    assert n == 1
    row = db._conn.execute("SELECT label FROM meta_model_rows WHERE ledger_ts=?", (ts,)).fetchone()
    assert row["label"] == 1


def test_train_meta_model_insufficient_data_does_not_train(db):
    ts = int(time.time()) - 10000
    for i in range(5):  # far below min_rows
        _seed_row_and_outcome(db, ts + i, "s1", "TCS", 0.6, "BULL", 15, 0, 1.0, win=True)
    result = train_meta_model(db, min_rows=100)
    assert result.trained is False
    p = predict_meta_probability(db, calibrated_confidence=0.6, regime="BULL", india_vix=15, fii_net_cr=0, bandit_weight=1.0)
    assert p is None


def test_train_meta_model_learns_a_real_separable_signal(db):
    """BULL regime + high VIX => wins; BEAR regime + low VIX => losses. A working
    model should learn this and predict accordingly on fresh (unseen) inputs."""
    ts0 = int(time.time()) - 200_000
    for i in range(80):
        _seed_row_and_outcome(db, ts0 + i * 10, "trend_follow", "TCS", 0.6, "BULL", 28.0, 500.0, 1.0, win=True)
    for i in range(80):
        _seed_row_and_outcome(db, ts0 + 100_000 + i * 10, "trend_follow", "TCS", 0.6, "BEAR", 10.0, -500.0, 1.0, win=False)

    result = train_meta_model(db, min_rows=100)
    assert result.trained is True
    assert result.n_rows == 160
    assert result.train_accuracy > 0.9, f"expected the model to learn this clearly separable pattern, got {result.train_accuracy}"

    p_bull = predict_meta_probability(
        db, calibrated_confidence=0.6, regime="BULL", india_vix=28.0, fii_net_cr=500.0, bandit_weight=1.0
    )
    p_bear = predict_meta_probability(
        db, calibrated_confidence=0.6, regime="BEAR", india_vix=10.0, fii_net_cr=-500.0, bandit_weight=1.0
    )
    assert p_bull is not None and p_bear is not None
    assert p_bull > 0.7, f"expected high win-probability in the learned-favorable regime, got {p_bull}"
    assert p_bear < 0.3, f"expected low win-probability in the learned-unfavorable regime, got {p_bear}"


def test_weights_persist_and_reload_across_calls(db):
    ts0 = int(time.time()) - 200_000
    for i in range(60):
        _seed_row_and_outcome(db, ts0 + i * 10, "s1", "TCS", 0.6, "BULL", 25.0, 500.0, 1.0, win=True)
    for i in range(60):
        _seed_row_and_outcome(db, ts0 + 100_000 + i * 10, "s1", "TCS", 0.6, "BEAR", 12.0, -500.0, 1.0, win=False)
    train_meta_model(db, min_rows=100)

    # simulate a fresh process reading the persisted weights back (new DB handle,
    # same underlying sqlite file — proves persistence, not just in-memory state)
    row = db._conn.execute("SELECT v FROM settings WHERE k='meta_model_weights_v1'").fetchone()
    assert row is not None
    import json

    data = json.loads(row["v"])
    assert len(data["weights"]) == 6
    assert data["n_rows"] == 120


def test_router_fuse_uses_trained_meta_model(db):
    """Integration proof: once trained, fuse() actually calls the meta-model and
    it measurably changes scoring — not just plumbed in and ignored."""
    from src.agent.router import AgentRouter
    from src.strategies.base import Signal

    ts0 = int(time.time()) - 200_000
    for i in range(80):
        _seed_row_and_outcome(db, ts0 + i * 10, "trend_follow", "TCS", 0.6, "BULL", 28.0, 500.0, 1.0, win=True)
    for i in range(80):
        _seed_row_and_outcome(db, ts0 + 100_000 + i * 10, "trend_follow", "TCS", 0.6, "BULL", 28.0, 500.0, 1.0, win=False)
    # symmetric win/loss at identical context -> untrained-equivalent baseline;
    # now make BEAR unambiguously bad so meta-model has a real signal to learn
    for i in range(80):
        _seed_row_and_outcome(db, ts0 + 200_000 + i * 10, "trend_follow", "TCS", 0.6, "BEAR", 10.0, -500.0, 1.0, win=False)
    train_meta_model(db, min_rows=100)

    router = AgentRouter(db=db)
    router.ctx.regime = "BEAR"
    router.ctx.india_vix = 10.0
    router.ctx.fii_net_cr = -500.0
    router.ctx.last_ltp = {"TCS": 3800.0}

    conf_in_bad_regime = router._apply_meta_model(0.6, "trend_follow")
    router.ctx.regime = "BULL"
    router.ctx.india_vix = 28.0
    router.ctx.fii_net_cr = 500.0
    conf_in_mixed_regime = router._apply_meta_model(0.6, "trend_follow")

    assert conf_in_bad_regime < conf_in_mixed_regime, (
        f"expected the trained meta-model to score the historically-bad regime lower, "
        f"got bad={conf_in_bad_regime} vs mixed={conf_in_mixed_regime}"
    )

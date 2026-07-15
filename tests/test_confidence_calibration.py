"""Confidence calibration — proves hand-picked confidence gets corrected against
realized outcomes, in both directions, with sane cold-start behavior.
"""
from __future__ import annotations

import os
import time

import pytest

from src.agent.confidence_calibration import calibrate_confidence, calibration_curve
from src.db.database import DB, DBConfig


@pytest.fixture
def db(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "t.db")
    return DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))


_ts_counter = [0]


def _seed_outcomes(db, strategy_id, confidence, win_rate, n, ret_mag=0.01):
    """Insert n labeled BUY signals at a fixed confidence, win_rate fraction winning."""
    wins = round(n * win_rate)
    base = int(time.time()) - 10_000_000
    with db.tx() as conn:
        for i in range(n):
            ret = ret_mag if i < wins else -ret_mag
            _ts_counter[0] += 1
            ts = base + _ts_counter[0] * 300
            conn.execute(
                """
                INSERT INTO strategy_signal_outcomes
                    (ledger_ts, strategy_id, symbol, signal, confidence, executed, entry_price, ret_15m, ret_1d, labeled_ts)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (ts, strategy_id, "TCS", "BUY", confidence, 1, 100.0, ret, ret, ts + 900),
            )


def test_overconfident_strategy_gets_pulled_down(db):
    # claims 0.9 confidence but actually wins only 35% of the time
    _seed_outcomes(db, "hype_strategy", confidence=0.9, win_rate=0.35, n=60)
    calibrated = calibrate_confidence(db, "hype_strategy", 0.9)
    assert calibrated < 0.7, f"expected overconfident strategy pulled well below 0.9, got {calibrated}"


def test_underconfident_strategy_gets_pulled_up(db):
    # modestly claims 0.55 but actually wins 80% of the time
    _seed_outcomes(db, "sandbagger", confidence=0.55, win_rate=0.80, n=60)
    calibrated = calibrate_confidence(db, "sandbagger", 0.55)
    assert calibrated > 0.65, f"expected underconfident strategy pulled well above 0.55, got {calibrated}"


def test_cold_start_returns_raw_confidence(db):
    # only 5 samples — nowhere near enough evidence to override the strategy's own number
    _seed_outcomes(db, "new_strategy", confidence=0.9, win_rate=0.0, n=5)
    calibrated = calibrate_confidence(db, "new_strategy", 0.9)
    assert calibrated == pytest.approx(0.9)


def test_no_db_returns_raw_confidence():
    assert calibrate_confidence(None, "anything", 0.73) == pytest.approx(0.73)


def test_thin_bucket_blends_toward_overall_win_rate(db):
    # plenty of overall history in other buckets, but almost nothing at exactly 0.8
    _seed_outcomes(db, "mixed", confidence=0.5, win_rate=0.6, n=40)
    _seed_outcomes(db, "mixed", confidence=0.8, win_rate=1.0, n=2)  # thin bucket, don't fully trust it
    calibrated = calibrate_confidence(db, "mixed", 0.8)
    # should NOT be pulled all the way to 1.0 off just 2 samples in that bucket
    assert calibrated < 0.9
    assert calibrated > 0.5


def test_calibration_curve_reports_per_bucket_stats(db):
    _seed_outcomes(db, "strat_a", confidence=0.6, win_rate=0.5, n=20)
    curve = calibration_curve(db, "strat_a")
    assert 0.6 in curve
    assert curve[0.6].n == 20
    assert curve[0.6].win_rate == pytest.approx(0.5, abs=0.05)


def test_well_calibrated_strategy_barely_moves(db):
    # claims 0.7, wins ~70% of the time — should stay close to 0.7
    _seed_outcomes(db, "honest_strategy", confidence=0.7, win_rate=0.70, n=60)
    calibrated = calibrate_confidence(db, "honest_strategy", 0.7)
    assert abs(calibrated - 0.7) < 0.1


def test_router_fuse_picks_the_calibrated_winner_not_the_raw_tie(db):
    """Integration proof: two signals with IDENTICAL raw confidence on different
    symbols (so SignalCombiner doesn't merge them into one meta-signal) — one
    strategy has a strong realized track record, the other a weak one. fuse() must
    pick the strategy with real evidence behind it, not coin-flip the raw tie."""
    from src.agent.router import AgentRouter
    from src.strategies.base import Signal

    _seed_outcomes(db, "fii_regime", confidence=0.65, win_rate=0.85, n=60)
    _seed_outcomes(db, "vwap_reversion", confidence=0.65, win_rate=0.25, n=60)

    router = AgentRouter(db=db)
    router.ctx.regime = "NEUTRAL"
    router.ctx.last_ltp = {"TCS": 3800.0, "INFY": 1500.0}

    signals = [
        Signal("fii_regime", "TCS", "BUY", "CNC", 0.65, "test"),
        Signal("vwap_reversion", "INFY", "BUY", "CNC", 0.65, "test"),
    ]
    chosen = router.fuse(signals, event_price=0.0, event_symbol="")
    assert chosen is not None
    assert chosen.strategy_id == "fii_regime", (
        f"expected calibration to favor the strategy with the real track record, got {chosen.strategy_id}"
    )
    assert chosen.symbol == "TCS"

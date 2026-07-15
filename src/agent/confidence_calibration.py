"""
Confidence calibration — maps each strategy's raw self-reported confidence to a
probability derived from its own realized outcome history (strategy_signal_outcomes),
so router.fuse() compares strategies on a common, evidence-based scale instead of
arbitrary hand-picked numbers (0.55, 0.62, 0.71, ...) baked into each strategy file.

Cold start / thin-data behavior mirrors the Bayesian-shrinkage pattern already used
in Kelly sizing and the bandit: trust the strategy's own number until there's real
evidence to correct it, and correct gradually as evidence accumulates — never let a
single lucky/unlucky small sample violently swing a strategy's effective confidence.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

from ..db.database import DB

_MIN_BUCKET_SAMPLES = int(os.getenv("CALIBRATION_MIN_BUCKET_SAMPLES", "8"))
_MIN_STRATEGY_SAMPLES = int(os.getenv("CALIBRATION_MIN_STRATEGY_SAMPLES", "20"))
_LOOKBACK = int(os.getenv("CALIBRATION_LOOKBACK", "300"))
_BUCKET_WIDTH = float(os.getenv("CALIBRATION_BUCKET_WIDTH", "0.1"))


@dataclass(frozen=True)
class BucketStats:
    n: int
    win_rate: float
    mean_return: float


def _bucket(confidence: float, width: float = _BUCKET_WIDTH) -> float:
    # +1e-9 epsilon guards against float division landing just under an integer
    # boundary (e.g. 0.6/0.1 == 5.999999999999999), which would floor into the
    # wrong bucket (0.5 instead of 0.6).
    b = math.floor(confidence / width + 1e-9) * width
    return round(min(max(b, 0.0), 0.9), 2)


def _fetch_outcomes(db: DB, strategy_id: str, lookback: int = _LOOKBACK) -> list:
    return list(
        db._conn.execute(
            """
            SELECT confidence, signal, ret_15m FROM strategy_signal_outcomes
            WHERE strategy_id=? AND confidence IS NOT NULL AND ret_15m IS NOT NULL
            ORDER BY ledger_ts DESC LIMIT ?
            """,
            (strategy_id, lookback),
        ).fetchall()
    )


def calibration_curve(db: DB, strategy_id: str) -> dict[float, BucketStats]:
    """bucket lower-edge -> realized stats for signals reported in that confidence range."""
    rows = _fetch_outcomes(db, strategy_id)
    buckets: dict[float, list[float]] = {}
    for r in rows:
        conf = float(r["confidence"])
        ret = float(r["ret_15m"])
        sig = str(r["signal"] or "BUY").upper()
        signed = ret if sig == "BUY" else -ret  # a SELL "wins" when price falls
        buckets.setdefault(_bucket(conf), []).append(signed)
    out: dict[float, BucketStats] = {}
    for b, rets in buckets.items():
        n = len(rets)
        wins = sum(1 for r in rets if r > 0)
        out[b] = BucketStats(n=n, win_rate=wins / n if n else 0.0, mean_return=sum(rets) / n if n else 0.0)
    return out


def calibrate_confidence(db: DB | None, strategy_id: str, raw_confidence: float) -> float:
    """
    Returns a calibrated confidence in [0, 1]. Behavior:
    - No db, no strategy_id, or raw_confidence <= 0: return raw_confidence unchanged.
    - Strategy has < _MIN_STRATEGY_SAMPLES total labeled signals: not enough evidence
      to correct anything yet — return raw_confidence unchanged (cold start).
    - Strategy has enough total samples but this specific confidence bucket is thin
      (< _MIN_BUCKET_SAMPLES): blend raw_confidence with the strategy's overall
      realized win rate, weighted by how much total evidence exists.
    - Bucket has enough samples: use the bucket's realized win rate, lightly shrunk
      toward raw_confidence to damp bucket-boundary noise on modest sample sizes.
    """
    if db is None or not strategy_id or raw_confidence <= 0:
        return raw_confidence
    curve = calibration_curve(db, strategy_id)
    total_n = sum(v.n for v in curve.values())
    if total_n < _MIN_STRATEGY_SAMPLES:
        return raw_confidence

    b = _bucket(raw_confidence)
    bucket = curve.get(b)
    if not bucket or bucket.n < _MIN_BUCKET_SAMPLES:
        overall_wins = sum(v.win_rate * v.n for v in curve.values())
        overall_wr = overall_wins / total_n if total_n else raw_confidence
        weight = min(1.0, total_n / (_MIN_STRATEGY_SAMPLES * 3))
        return raw_confidence * (1 - weight) + overall_wr * weight

    shrink = min(1.0, bucket.n / (_MIN_BUCKET_SAMPLES * 4))
    return bucket.win_rate * shrink + raw_confidence * (1 - shrink)

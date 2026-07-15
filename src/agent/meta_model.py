"""
Meta-model — replaces "weighted argmax of calibrated confidence" with a learned
decision function over context (regime, VIX, FII flow, bandit weight) + the
strategy's own calibrated confidence, predicting P(trade profitable after costs).

Pure-numpy logistic regression (same house style as ppo_trainer.py — no new
dependency). Cold-start behavior matches confidence_calibration.py and Kelly
sizing: with too little labeled training data, predict_meta_probability()
returns None and callers must fall back to the calibrated confidence unchanged.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import numpy as np

from ..db.database import DB

_MIN_TRAIN_ROWS = int(os.getenv("META_MODEL_MIN_TRAIN_ROWS", "100"))
_EPOCHS = int(os.getenv("META_MODEL_EPOCHS", "300"))
_LR = float(os.getenv("META_MODEL_LR", "0.1"))
_L2 = float(os.getenv("META_MODEL_L2", "0.01"))
_WEIGHTS_KEY = "meta_model_weights_v1"

FEATURE_NAMES = ["bias", "calibrated_confidence", "regime", "vix_scaled", "fii_scaled", "bandit_weight"]
N_FEATURES = len(FEATURE_NAMES)


def regime_to_numeric(regime: str) -> float:
    from .regime_classifier import normalize_regime

    r = normalize_regime(regime or "SIDEWAYS")
    return {"BULL": 1.0, "BEAR": -1.0, "HIGH_VOL": 0.5}.get(r, 0.0)


def build_feature_vector(
    *,
    calibrated_confidence: float,
    regime: str,
    india_vix: float,
    fii_net_cr: float,
    bandit_weight: float,
) -> np.ndarray:
    return np.array(
        [
            1.0,
            max(0.0, min(1.0, calibrated_confidence)),
            regime_to_numeric(regime),
            max(-2.0, min(2.0, india_vix / 25.0)),
            max(-2.0, min(2.0, fii_net_cr / 3000.0)),
            max(0.0, min(3.0, bandit_weight)),
        ],
        dtype=np.float64,
    )


def record_meta_row(
    db: DB,
    *,
    ledger_ts: int,
    strategy_id: str,
    symbol: str,
    raw_confidence: float,
    calibrated_confidence: float,
    regime: str,
    india_vix: float,
    fii_net_cr: float,
    bandit_weight: float,
) -> None:
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO meta_model_rows
                (ts, ledger_ts, strategy_id, symbol, raw_confidence, calibrated_confidence,
                 regime, india_vix, fii_net_cr, bandit_weight, label)
            VALUES (?,?,?,?,?,?,?,?,?,?,NULL)
            """,
            (
                int(time.time()), ledger_ts, strategy_id, symbol,
                raw_confidence, calibrated_confidence, regime, india_vix, fii_net_cr, bandit_weight,
            ),
        )


def label_meta_rows(db: DB, lookback: int = 2000) -> int:
    """Fill in win/loss labels for meta_model_rows once strategy_signal_outcomes
    has scored the matching ledger row (joined by ledger_ts + strategy_id)."""
    rows = db._conn.execute(
        """
        SELECT m.id, m.ledger_ts, m.strategy_id
        FROM meta_model_rows m
        WHERE m.label IS NULL
        ORDER BY m.ts DESC LIMIT ?
        """,
        (lookback,),
    ).fetchall()
    n = 0
    for r in rows:
        outcome = db._conn.execute(
            "SELECT ret_15m, signal FROM strategy_signal_outcomes WHERE ledger_ts=? AND strategy_id=?",
            (r["ledger_ts"], r["strategy_id"]),
        ).fetchone()
        if outcome is None or outcome["ret_15m"] is None:
            continue
        ret = float(outcome["ret_15m"])
        sig = str(outcome["signal"] or "BUY").upper()
        signed = ret if sig == "BUY" else -ret
        label = 1 if signed > 0 else 0
        with db.tx() as conn:
            conn.execute("UPDATE meta_model_rows SET label=? WHERE id=?", (label, r["id"]))
        n += 1
    return n


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _train_logreg(X: np.ndarray, y: np.ndarray, *, epochs: int = _EPOCHS, lr: float = _LR, l2: float = _L2) -> np.ndarray:
    n, d = X.shape
    w = np.zeros(d, dtype=np.float64)
    for _ in range(epochs):
        z = X @ w
        p = _sigmoid(z)
        grad = X.T @ (p - y) / n + l2 * w
        w -= lr * grad
    return w


@dataclass(frozen=True)
class MetaTrainResult:
    trained: bool
    n_rows: int
    train_accuracy: float
    weights: list[float]


def train_meta_model(db: DB, *, min_rows: int = _MIN_TRAIN_ROWS) -> MetaTrainResult:
    label_meta_rows(db)
    rows = db._conn.execute(
        """
        SELECT calibrated_confidence, regime, india_vix, fii_net_cr, bandit_weight, label
        FROM meta_model_rows WHERE label IS NOT NULL ORDER BY ts DESC LIMIT 3000
        """
    ).fetchall()
    if len(rows) < min_rows:
        return MetaTrainResult(trained=False, n_rows=len(rows), train_accuracy=0.0, weights=[])

    X = np.stack(
        [
            build_feature_vector(
                calibrated_confidence=float(r["calibrated_confidence"] or 0.5),
                regime=str(r["regime"] or "SIDEWAYS"),
                india_vix=float(r["india_vix"] or 15.0),
                fii_net_cr=float(r["fii_net_cr"] or 0.0),
                bandit_weight=float(r["bandit_weight"] or 1.0),
            )
            for r in rows
        ]
    )
    y = np.array([int(r["label"]) for r in rows], dtype=np.float64)

    w = _train_logreg(X, y)
    preds = (_sigmoid(X @ w) >= 0.5).astype(np.float64)
    acc = float((preds == y).mean())

    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (_WEIGHTS_KEY, json.dumps({"weights": w.tolist(), "n_rows": len(rows), "trained_ts": int(time.time())})),
        )
    return MetaTrainResult(trained=True, n_rows=len(rows), train_accuracy=acc, weights=w.tolist())


def predict_meta_probability(
    db: DB | None,
    *,
    calibrated_confidence: float,
    regime: str,
    india_vix: float,
    fii_net_cr: float,
    bandit_weight: float,
) -> float | None:
    """Returns a predicted win-probability in [0,1], or None if the model hasn't
    been trained yet (caller must fall back to calibrated_confidence unchanged)."""
    if db is None:
        return None
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (_WEIGHTS_KEY,)).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["v"])
        w = np.array(data["weights"], dtype=np.float64)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if w.shape[0] != N_FEATURES:
        return None
    x = build_feature_vector(
        calibrated_confidence=calibrated_confidence,
        regime=regime,
        india_vix=india_vix,
        fii_net_cr=fii_net_cr,
        bandit_weight=bandit_weight,
    )
    return float(_sigmoid(x @ w))

"""Strategy lifecycle — candidacy → probation → full → auto-demotion."""
from __future__ import annotations

import logging
import os
import time
from typing import Literal

from ..db.database import DB
from ..agent.strategy_stats import binomial_edge_p_value, strategy_fitness
from ..risk.risk_metrics import RiskFitness

logger = logging.getLogger("bharatquant.lifecycle")

LifecycleState = Literal["candidacy", "probation", "full", "demoted", "shadow_only"]

_CANDIDACY_MIN_SIGNALS = int(os.getenv("LIFECYCLE_CANDIDACY_MIN_SIGNALS", "100"))
_PROBATION_MIN_TRADES = int(os.getenv("LIFECYCLE_PROBATION_MIN_TRADES", "20"))
_PROBATION_ALLOC = float(os.getenv("LIFECYCLE_PROBATION_ALLOC", "0.10"))
_MIN_SORTINO_PROMOTE = float(os.getenv("LIFECYCLE_MIN_SORTINO", "0.15"))
_MIN_CALMAR_PROMOTE = float(os.getenv("LIFECYCLE_MIN_CALMAR", "0.35"))
_DEMOTE_SORTINO = float(os.getenv("LIFECYCLE_DEMOTE_SORTINO", "0.0"))
_DEMOTE_CALMAR = float(os.getenv("LIFECYCLE_DEMOTE_CALMAR", "0.25"))

# Hand-written registry strategies ship at full allocation
_CORE_FULL = {
    "opening_range", "affordable_momentum", "fast_snapshot", "vwap_reversion",
    "combined_momentum", "turtle_breakout", "gift_gap", "short_term_reversal",
    "pairs_stat_arb", "bulk_accumulation", "insider_cluster", "quality_momentum",
    "macro_confluence", "gift_fii_sync", "volume_breakout", "bollinger_squeeze",
    "dual_momentum_pro", "fii_divergence", "vwap_volume_confirm", "crude_energy_beta",
    "rsi_regime_adaptive", "adaptive_alpha", "strategy_lab", "sector_rotation",
    "options_greeks", "connors_ibs", "crabel_nr7", "zscore_reversion", "momentum_consensus",
    "ema_cross_rsi", "liquidity_sweep", "signal_combiner", "stop_loss_guard", "fii_regime",
}


def _default_state(strategy_id: str) -> LifecycleState:
    if strategy_id.startswith(("learned_", "custom_")):
        return "candidacy"
    if strategy_id in _CORE_FULL:
        return "full"
    return "candidacy"


def ensure_lifecycle_row(db: DB, strategy_id: str) -> str:
    row = db._conn.execute(
        "SELECT state FROM strategy_lifecycle WHERE strategy_id=?", (strategy_id,)
    ).fetchone()
    if row:
        return str(row["state"])
    state = _default_state(strategy_id)
    now = int(time.time())
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO strategy_lifecycle(strategy_id, state, entered_ts, shadow_signals, probation_trades, last_fitness)
            VALUES (?,?,?,?,?,?)
            """,
            (strategy_id, state, now, 0, 0, 0.0),
        )
    return state


def get_lifecycle_state(db: DB, strategy_id: str) -> LifecycleState:
    return ensure_lifecycle_row(db, strategy_id)  # type: ignore[return-value]


def allocation_fraction(db: DB, strategy_id: str) -> float:
    state = get_lifecycle_state(db, strategy_id)
    if state in ("candidacy", "demoted", "shadow_only"):
        return 0.0
    if state == "probation":
        return _PROBATION_ALLOC
    return 1.0


def can_allocate_capital(db: DB, strategy_id: str) -> tuple[bool, str]:
    frac = allocation_fraction(db, strategy_id)
    if frac <= 0:
        return False, f"lifecycle_{get_lifecycle_state(db, strategy_id)}"
    return True, "ok"


def record_shadow_signal(db: DB, strategy_id: str) -> None:
    ensure_lifecycle_row(db, strategy_id)
    with db.tx() as conn:
        conn.execute(
            "UPDATE strategy_lifecycle SET shadow_signals = shadow_signals + 1 WHERE strategy_id=?",
            (strategy_id,),
        )


def record_probation_trade(db: DB, strategy_id: str) -> None:
    state = get_lifecycle_state(db, strategy_id)
    if state != "probation":
        return
    with db.tx() as conn:
        conn.execute(
            "UPDATE strategy_lifecycle SET probation_trades = probation_trades + 1 WHERE strategy_id=?",
            (strategy_id,),
        )


def _transition(db: DB, strategy_id: str, new_state: LifecycleState, fitness: float) -> None:
    now = int(time.time())
    with db.tx() as conn:
        conn.execute(
            """
            UPDATE strategy_lifecycle
            SET state=?, entered_ts=?, last_fitness=?, probation_trades=0, demoted_ts=?
            WHERE strategy_id=?
            """,
            (
                new_state,
                now,
                fitness,
                now if new_state in ("demoted", "shadow_only") else None,
                strategy_id,
            ),
        )
    logger.info("lifecycle_transition", extra={"strategy": strategy_id, "state": new_state, "fitness": fitness})


def _passes_promotion_gate(fit: RiskFitness, wins: int, n: int, *, min_samples: int = 20) -> bool:
    if n < min_samples:
        return False
    if fit.composite <= 0:
        return False
    if fit.sortino < _MIN_SORTINO_PROMOTE or fit.calmar < _MIN_CALMAR_PROMOTE:
        return False
    return binomial_edge_p_value(wins, n) <= 0.05


def evaluate_lifecycle_transitions(db: DB) -> list[dict]:
    """Nightly/learning-pass governance — promote or demote by risk-adjusted fitness."""
    from ..agent.strategy_stats import strategy_performance

    results: list[dict] = []
    rows = db._conn.execute("SELECT strategy_id, state, shadow_signals, probation_trades FROM strategy_lifecycle").fetchall()
    for r in rows:
        sid = str(r["strategy_id"])
        state = str(r["state"])
        fit = strategy_fitness(db, sid)
        perf = strategy_performance(db, sid)
        changed = False

        if state == "candidacy":
            if int(r["shadow_signals"]) >= _CANDIDACY_MIN_SIGNALS and _passes_promotion_gate(
                fit, perf.wins, perf.sample_count, min_samples=_CANDIDACY_MIN_SIGNALS // 5
            ):
                _transition(db, sid, "probation", fit.composite)
                changed = True
                state = "probation"
        elif state == "probation":
            if int(r["probation_trades"]) >= _PROBATION_MIN_TRADES and _passes_promotion_gate(fit, perf.wins, perf.sample_count):
                _transition(db, sid, "full", fit.composite)
                changed = True
                state = "full"
        elif state == "full":
            if perf.sample_count >= 20 and (fit.sortino < _DEMOTE_SORTINO or fit.calmar < _DEMOTE_CALMAR):
                _transition(db, sid, "demoted", fit.composite)
                changed = True
                state = "demoted"
        elif state in ("demoted", "shadow_only"):
            if fit.composite > 0.5 and _passes_promotion_gate(fit, perf.wins, perf.sample_count):
                _transition(db, sid, "probation", fit.composite)
                changed = True

        if changed or fit.n >= 10:
            with db.tx() as conn:
                conn.execute(
                    "UPDATE strategy_lifecycle SET last_fitness=? WHERE strategy_id=?",
                    (fit.composite, sid),
                )
        results.append({"strategy_id": sid, "state": state, "fitness": fit.composite, "changed": changed})
    return results

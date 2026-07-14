"""Shadow trades — log all fuse candidates for credit assignment (not only winners)."""
from __future__ import annotations

import time

from ..db.database import DB
from ..strategies.base import Signal


def record_shadow(db: DB, sig: Signal, price: float, *, fuse_rank: int | None = None) -> None:
    reason = sig.reason
    if fuse_rank is not None:
        reason = f"{sig.reason}|fuse_rank={fuse_rank}"
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO shadow_trades(ts, strategy_id, symbol, action, confidence, price, reason)
            VALUES (?,?,?,?,?,?,?)
            """,
            (int(time.time()), sig.strategy_id, sig.symbol, sig.action, sig.confidence, price, reason),
        )


def record_fuse_candidates(
    db: DB,
    scored: list[tuple[float, Signal]],
    chosen: Signal | None,
    price: float,
) -> None:
    """Log every regime-filtered fuse competitor — bandit learns from non-winners too."""
    from .strategy_lifecycle import record_shadow_signal

    for rank, (_score, sig) in enumerate(sorted(scored, key=lambda x: -x[0])):
        is_winner = (
            chosen is not None
            and sig.strategy_id == chosen.strategy_id
            and sig.symbol == chosen.symbol
            and sig.action == chosen.action
        )
        if is_winner:
            continue
        record_shadow(db, sig, price, fuse_rank=rank + 1)
        record_shadow_signal(db, sig.strategy_id)

"""Record RL transitions from agent decisions (observer mode — learns every activity)."""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from ..db.database import DB
from ..rl.reward import RewardConfig, compute_reward, compute_trade_reward
from ..rl.rl_buffer import RLBuffer
from ..rl.state_encoder import encode_state, index_action
from ..strategies.base import Signal

logger = logging.getLogger("bharatquant.rl_observer")

_RL_VERSION = os.getenv("RL_ACTIVE_VERSION", "ppo_v1")
_ENABLED = os.getenv("RL_OBSERVER_ENABLED", "true").lower() in ("1", "true", "yes")


class RLObserver:
    def __init__(self, db: DB) -> None:
        self.db = db
        self.buffer = RLBuffer(db)
        self._last_state: dict[str, list[float]] = {}
        self._reward_cfg = RewardConfig(drawdown_penalty=float(os.getenv("RL_DRAWDOWN_PENALTY", "0.5")))

    def snapshot_before(self, ctx: Any, sig: Signal, score: float = 0.0) -> None:
        if not _ENABLED:
            return
        key = sig.symbol
        self._last_state[key] = encode_state(ctx, symbol=sig.symbol, confidence=sig.confidence, score=score)

    def record_skip(
        self,
        ctx: Any,
        sig: Signal,
        *,
        reason: str,
        executed: bool = False,
    ) -> None:
        if not _ENABLED:
            return
        prev = self._last_state.pop(sig.symbol, None)
        if prev is None:
            return
        action = index_action(0)
        next_state = encode_state(ctx, symbol=sig.symbol, confidence=sig.confidence)
        self.buffer.push(
            _RL_VERSION,
            sig.symbol,
            {str(i): v for i, v in enumerate(prev)},
            action,
            -0.001 if reason else 0.0,
            {str(i): v for i, v in enumerate(next_state)},
            done=False,
        )
        logger.debug("rl_skip_transition", extra={"symbol": sig.symbol, "reason": reason, "executed": executed})

    def record_outcome(
        self,
        ctx: Any,
        sig: Signal,
        *,
        executed: bool,
        daily_return: float = 0.0,
        drawdown: float = 0.0,
        realized_pnl: float = 0.0,
        cost_basis: float = 0.0,
    ) -> int:
        if not _ENABLED:
            return 0
        prev = self._last_state.pop(sig.symbol, None)
        if prev is None:
            return 0
        action = index_action(1 if sig.action == "BUY" and executed else (2 if sig.action == "SELL" and executed else 0))
        if executed and sig.action == "SELL" and cost_basis > 0:
            reward = compute_trade_reward(realized_pnl, cost_basis, self._reward_cfg)
        elif executed:
            reward = compute_reward(daily_return, drawdown, self._reward_cfg)
        else:
            reward = -0.001
        next_state = encode_state(ctx, symbol=sig.symbol, confidence=sig.confidence)
        self.buffer.push(
            _RL_VERSION,
            sig.symbol,
            {str(i): v for i, v in enumerate(prev)},
            action,
            reward,
            {str(i): v for i, v in enumerate(next_state)},
            done=sig.action == "SELL" and executed,
        )
        logger.debug("rl_transition", extra={"symbol": sig.symbol, "action": action, "reward": reward})
        return self._transition_count()

    def _transition_count(self) -> int:
        row = self.db._conn.execute(
            "SELECT COUNT(*) AS c FROM rl_transitions WHERE version=?",
            (_RL_VERSION,),
        ).fetchone()
        return int(row["c"]) if row else 0

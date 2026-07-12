"""Fuse strategy signals — pick best after costs; RL boosts when policy agrees."""
from __future__ import annotations

import os
from typing import List, Optional

from ..strategies.base import MarketContext, Signal
from ..risk.risk_engine import RiskEngine, risk_config_from_env
from ..risk.event_calendar import mis_allowed_today
from ..data.asm_gsm_filter import is_excluded
from ..risk.sector_limits import can_add_sector
from ..agent.regime_classifier import regime_strategy_whitelist
from ..agent.var_breaker import var_breach
from ..agent.shadow_trades import record_shadow
from ..agent.kelly_sizing import rupees_from_kelly
from ..db.database import DB
from ..rl.rl_agent import RLAgent
from ..rl.state_encoder import encode_state


class AgentRouter:
    def __init__(self, db: DB | None = None) -> None:
        self.db = db
        self.ctx = MarketContext()
        self.risk = RiskEngine(risk_config_from_env())
        self._weights: dict[str, float] = {}
        self._returns: list[float] = []
        self._shadow_mode = os.getenv("SHADOW_MODE", "false").lower() in ("1", "true", "yes")
        self._rl_agent = RLAgent() if os.getenv("RL_AGENT_ENABLED", "true").lower() in ("1", "true", "yes") else None

    def set_weight(self, strategy_id: str, w: float) -> None:
        self._weights[strategy_id] = max(0.0, w)

    def record_return(self, ret: float) -> None:
        self._returns.append(ret)
        if len(self._returns) > 90:
            self._returns = self._returns[-90:]

    def fuse(self, signals: List[Signal]) -> Optional[Signal]:
        if not signals:
            return None
        allowed = regime_strategy_whitelist(self.ctx.regime)
        if self.ctx.regime == "RISK_OFF":
            hedges = [s for s in signals if s.action == "HEDGE" and s.strategy_id in allowed]
            if hedges:
                return max(hedges, key=lambda s: s.confidence)
            return None
        scored = []
        for s in signals:
            if s.strategy_id not in allowed:
                continue
            if s.action in ("BUY", "SELL", "HEDGE"):
                w = self._weights.get(s.strategy_id, 1.0)
                scored.append((s.confidence * w, s))
        if not scored:
            return None
        chosen = max(scored, key=lambda x: x[0])[1]
        return self._apply_rl_boost(chosen)

    def _apply_rl_boost(self, chosen: Signal) -> Optional[Signal]:
        if not self._rl_agent or not self._rl_agent.is_learning_enabled():
            return chosen
        if chosen.action not in ("BUY", "SELL"):
            return chosen
        vec = encode_state(self.ctx, symbol=chosen.symbol, confidence=chosen.confidence, score=chosen.confidence)
        state = {str(i): v for i, v in enumerate(vec)}
        rl_action = self._rl_agent.act(state)
        expected = "buy" if chosen.action == "BUY" else "sell"
        if rl_action == expected:
            return Signal(
                chosen.strategy_id,
                chosen.symbol,
                chosen.action,
                chosen.rail,
                min(0.98, chosen.confidence * 1.08),
                f"{chosen.reason}+rl_agree",
                meta=chosen.meta,
            )
        min_veto = int(os.getenv("RL_MIN_TRANSITIONS_VETO", "80"))
        n = 0
        if self.db:
            row = self.db._conn.execute("SELECT COUNT(*) AS c FROM rl_transitions").fetchone()
            n = int(row["c"]) if row else 0
        if n >= min_veto and chosen.confidence < 0.88:
            return None
        return chosen

    def risk_veto(self, signal: Signal, portfolio: dict) -> tuple[bool, str]:
        if signal.action == "SELL":
            return True, "ok"
        if var_breach(self._returns, float(portfolio.get("total_equity", 0))):
            return False, "var_circuit_breaker"
        ok, reason = self.risk.can_open_new(portfolio)
        if not ok and signal.action == "BUY":
            return False, reason
        if signal.action == "BUY" and self.db and is_excluded(self.db, signal.symbol):
            return False, "asm_gsm_excluded"
        if signal.action == "BUY" and signal.rail.upper() == "MIS" and self.db and not mis_allowed_today(self.db):
            return False, "calendar_mis_blocked"
        max_trade = float(os.getenv("MAX_RUPEES_PER_TRADE", "1000"))
        if signal.action == "BUY":
            kelly_r = rupees_from_kelly(
                float(portfolio.get("total_equity", 0)),
                0.55,
                1.2,
                1.0,
                max_trade,
            )
            if kelly_r < 50:
                return False, "kelly_too_small"
            if self.db:
                ok_sec, sec_reason = can_add_sector(self.db, signal.symbol, kelly_r)
                if not ok_sec:
                    return False, sec_reason
        return True, "ok"

    def maybe_shadow(self, sig: Signal, price: float, executed: bool) -> None:
        if self._shadow_mode and self.db and not executed:
            record_shadow(self.db, sig, price)

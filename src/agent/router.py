"""Fuse strategy signals — pick best after costs; no LLM."""
from __future__ import annotations

import os
from typing import List, Optional

from ..strategies.base import MarketContext, Signal
from ..risk.risk_engine import RiskEngine, RiskConfig
from ..risk.event_calendar import mis_allowed_today
from ..data.asm_gsm_filter import is_excluded
from ..risk.sector_limits import can_add_sector
from ..agent.regime_classifier import regime_strategy_whitelist
from ..agent.var_breaker import var_breach
from ..agent.shadow_trades import record_shadow
from ..agent.kelly_sizing import rupees_from_kelly
from ..db.database import DB


class AgentRouter:
    def __init__(self, db: DB | None = None) -> None:
        self.db = db
        self.ctx = MarketContext()
        self.risk = RiskEngine(
            RiskConfig(
                stop_loss_percent=float(os.getenv("STOP_LOSS_PCT", "4")),
                max_daily_loss_percent=float(os.getenv("MAX_DAILY_LOSS_PCT", "2")),
                max_daily_loss_rupees=float(os.getenv("MAX_DAILY_LOSS_RUPEES", "2000")),
                max_positions=int(os.getenv("MAX_POSITIONS", "5")),
            )
        )
        self._weights: dict[str, float] = {}
        self._returns: list[float] = []
        self._shadow_mode = os.getenv("SHADOW_MODE", "false").lower() in ("1", "true", "yes")

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
        return max(scored, key=lambda x: x[0])[1]

    def risk_veto(self, signal: Signal, portfolio: dict) -> tuple[bool, str]:
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
            if kelly_r < 100:
                return False, "kelly_too_small"
            if self.db:
                ok_sec, sec_reason = can_add_sector(self.db, signal.symbol, kelly_r)
                if not ok_sec:
                    return False, sec_reason
        if signal.action == "BUY" and portfolio.get("pending_amount", 0) > max_trade:
            return False, "max_rupees_per_trade"
        return True, "ok"

    def maybe_shadow(self, sig: Signal, price: float, executed: bool) -> None:
        if self._shadow_mode and self.db and not executed:
            record_shadow(self.db, sig, price)

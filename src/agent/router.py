"""Fuse strategy signals — pick best after costs; RL boosts when policy agrees."""
from __future__ import annotations

import os
from typing import List, Optional

from ..strategies.base import MarketContext, Signal
from ..risk.risk_engine import RiskEngine, risk_config_from_env
from ..risk.event_calendar import mis_allowed_today
from ..data.asm_gsm_filter import is_excluded
from ..risk.sector_limits import can_add_sector
from ..ops.trade_sizing import can_buy_whole_share
from ..agent.regime_classifier import normalize_regime, regime_strategy_whitelist
from ..agent.var_breaker import var_breach
from ..agent.shadow_trades import record_shadow
from ..agent.kelly_sizing import rupees_from_kelly, kelly_fraction_for_strategy
from ..db.database import DB
from ..rl.rl_agent import RLAgent
from ..rl.state_encoder import encode_state
from .signal_combiner import SignalCombiner


class AgentRouter:
    def __init__(self, db: DB | None = None) -> None:
        self.db = db
        self.ctx = MarketContext()
        self.risk = RiskEngine(risk_config_from_env())
        self._weights: dict[str, float] = {}
        self._returns: list[float] = []
        self._shadow_mode = os.getenv("SHADOW_MODE", "false").lower() in ("1", "true", "yes")
        self._rl_agent = RLAgent(db=db) if os.getenv("RL_AGENT_ENABLED", "true").lower() in ("1", "true", "yes") else None
        self._combiner = SignalCombiner()

    def set_weight(self, strategy_id: str, w: float) -> None:
        self._weights[strategy_id] = max(0.0, w)

    def _adjust_confidence(self, signal: Signal) -> float:
        """OBI + corporate profit cues → fused confidence."""
        sym = signal.symbol.replace("NSE:", "")
        obi = float(self.ctx.orderbook_imbalance.get(sym, 0) or 0)
        conf = signal.confidence
        if signal.action == "BUY":
            conf *= 1.0 + max(-0.1, min(0.1, obi * 0.12))
        elif signal.action == "SELL":
            conf *= 1.0 + max(-0.1, min(0.1, -obi * 0.12))

        from ..intelligence.corporate_activity import corporate_profit_tilt

        mult, reasons = corporate_profit_tilt(signal.symbol, self.ctx)
        conf *= mult
        if signal.action == "BUY" and mult < 0.8:
            conf = min(conf, 0.52)
        if reasons:
            signal.meta = {**(signal.meta or {}), "corp_profit": reasons, "corp_mult": round(mult, 3)}
        return min(0.98, max(0.0, conf))

    def _obi_adjust_confidence(self, signal: Signal) -> float:
        """Backward-compatible alias."""
        return self._adjust_confidence(signal)

    def _corporate_adjust_confidence(self, signal: Signal) -> float:
        """Backward-compatible alias."""
        return self._adjust_confidence(signal)

    def record_return(self, ret: float) -> None:
        self._returns.append(ret)
        if len(self._returns) > 90:
            self._returns = self._returns[-90:]

    def fuse(self, signals: List[Signal], *, event_price: float = 0.0, event_symbol: str = "") -> Optional[Signal]:
        if not signals:
            return None
        allowed = regime_strategy_whitelist(self.ctx.regime)
        norm = normalize_regime(self.ctx.regime)
        if norm == "BEAR":
            hedges = [s for s in signals if s.action == "HEDGE" and s.strategy_id in allowed]
            if hedges:
                return self._apply_rl_boost(max(hedges, key=lambda s: s.confidence))
        max_trade = float(os.getenv("MAX_RUPEES_PER_TRADE", "1000"))
        from ..intelligence.strategy_learning import strategy_weight_multiplier

        learned = getattr(self.ctx, "strategy_learn_weights", {}) or {}
        pool_signals: list[Signal] = []
        for s in signals:
            if s.strategy_id not in allowed and not s.strategy_id.startswith(("custom_", "learned_")):
                continue
            if s.action in ("BUY", "SELL", "HEDGE"):
                pool_signals.append(s)
        combined = self._combiner.combine(
            pool_signals, self.ctx, self._weights, self._adjust_confidence
        )
        scored: list[tuple[float, Signal]] = []
        for s in combined:
            w = self._weights.get(s.strategy_id, 1.0)
            conf = s.confidence if s.strategy_id == "signal_combiner" else self._adjust_confidence(s)
            learn_mult = strategy_weight_multiplier(learned, s.strategy_id)
            if self.db:
                from ..agent.strategy_lifecycle import get_lifecycle_state
                from ..intelligence.historical_screen import candidacy_priority_multiplier

                if get_lifecycle_state(self.db, s.strategy_id) == "candidacy":
                    learn_mult *= candidacy_priority_multiplier(self.db, s.strategy_id)
            scored.append((conf * w * learn_mult, s))
        if not scored:
            return None

        def _ltp(sig: Signal) -> float:
            if event_symbol and sig.symbol == event_symbol and event_price > 0:
                return event_price
            return float(self.ctx.last_ltp.get(sig.symbol, 0))

        affordable = []
        for score, s in scored:
            if s.action != "BUY":
                affordable.append((score, s))
                continue
            ltp = _ltp(s)
            cap = max_trade
            if self.db:
                from ..ops.trade_sizing import deploy_cap_inr

                cash_row = self.db._conn.execute(
                    "SELECT IFNULL(SUM(delta),0) c FROM cash_ledger"
                ).fetchone()
                cash = float(cash_row["c"]) if cash_row else 0.0
                cap = deploy_cap_inr(self.db, cash)
            if ltp <= 0 or can_buy_whole_share(ltp, cap):
                affordable.append((score, s))
        pool = affordable if affordable else scored
        if self.db:
            from ..agent.strategy_lifecycle import can_allocate_capital

            executable = [(sc, s) for sc, s in pool if can_allocate_capital(self.db, s.strategy_id)[0]]
            if executable:
                pool = executable
            elif pool:
                from ..agent.shadow_trades import record_fuse_candidates

                record_fuse_candidates(self.db, pool, None, event_price)
                return None
        if not pool:
            return None
        chosen = max(pool, key=lambda x: x[0])[1]
        if self.db:
            from ..agent.shadow_trades import record_fuse_candidates

            record_fuse_candidates(self.db, affordable if affordable else scored, chosen, event_price)
        return self._apply_rl_boost(chosen)

    def _apply_rl_boost(self, chosen: Signal) -> Optional[Signal]:
        if not self._rl_agent or not self._rl_agent.is_learning_enabled():
            return chosen
        if chosen.action not in ("BUY", "SELL"):
            return chosen
        vec = encode_state(
            self.ctx,
            symbol=chosen.symbol,
            confidence=chosen.confidence,
            score=chosen.confidence,
            db=self.db,
        )
        state = {str(i): v for i, v in enumerate(vec)}
        ltp = float(self.ctx.last_ltp.get(chosen.symbol, 0))
        cash = 0.0
        if self.db:
            cash = float(self.db._conn.execute("SELECT IFNULL(SUM(delta),0) FROM cash_ledger").fetchone()[0])
        has_pos = chosen.symbol.replace("NSE:", "") in (self.ctx.positions or {})
        rl_action = self._rl_agent.act(state, chosen.symbol, ltp=ltp, cash=cash, has_position=has_pos)
        expected = "buy" if chosen.action == "BUY" else "sell"
        rl_primary = os.getenv("RL_PRIMARY_MODE", "true").lower() in ("1", "true", "yes")

        if rl_action == expected:
            boost = 1.15 if rl_primary and self._rl_agent.primary_ready() else 1.08
            return Signal(
                chosen.strategy_id,
                chosen.symbol,
                chosen.action,
                chosen.rail,
                min(0.98, chosen.confidence * boost),
                f"{chosen.reason}+rl_agree",
                meta=chosen.meta,
            )

        min_veto = int(os.getenv("RL_MIN_TRANSITIONS_VETO", "80"))
        paper_learn = os.getenv("TRADING_PHASE", "paper_learn") == "paper_learn"
        if paper_learn:
            min_veto = max(min_veto, 200)
        n = self._rl_agent.transition_count()

        if rl_primary and self._rl_agent.primary_ready() and rl_action == "hold" and chosen.action == "BUY":
            if chosen.confidence < 0.92:
                return None

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
        if signal.action == "BUY" and self.db:
            from ..intelligence.strategy_correlation import is_strategy_disabled

            if is_strategy_disabled(self.db, signal.strategy_id):
                return False, "strategy_disabled_correlation"
        max_trade = float(os.getenv("MAX_RUPEES_PER_TRADE", "1000"))
        if signal.action == "BUY":
            from ..agent.strategy_lifecycle import allocation_fraction, can_allocate_capital, record_probation_trade

            ok_lc, lc_reason = can_allocate_capital(self.db, signal.strategy_id) if self.db else (True, "ok")
            if not ok_lc:
                return False, lc_reason
            lc_frac = allocation_fraction(self.db, signal.strategy_id) if self.db else 1.0
            wr, aw, al, wr_var = kelly_fraction_for_strategy(self.db, signal.strategy_id) if self.db else (0.52, 1.0, 1.0, 0.25)
            kelly_r = rupees_from_kelly(
                float(portfolio.get("total_equity", 0)),
                wr,
                aw,
                al,
                max_trade,
                wr_variance=wr_var,
                lifecycle_frac=lc_frac,
            )
            if kelly_r < 50:
                return False, "kelly_too_small"
            if self.db:
                ok_sec, sec_reason = can_add_sector(self.db, signal.symbol, kelly_r)
                if not ok_sec:
                    return False, sec_reason
                from ..risk.portfolio_beta import can_add_beta_exposure

                ok_beta, beta_reason = can_add_beta_exposure(
                    self.db, signal.symbol, kelly_r, float(portfolio.get("total_equity", 0))
                )
                if not ok_beta:
                    return False, beta_reason
        return True, "ok"

    def maybe_shadow(self, sig: Signal, price: float, executed: bool) -> None:
        if self._shadow_mode and self.db and not executed:
            record_shadow(self.db, sig, price)

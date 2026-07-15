"""Event-driven execution handler — paper or live."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from ..accounting.fifo_lots import close_lots_fifo, load_positions_ctx, open_lot
from ..alerts.webhook import build_delivery, publish_strategy_alert, send_telegram
from ..agent.router import AgentRouter
from ..costs.cost_engine import CostEngine
from ..data.asm_gsm_filter import is_excluded
from ..db.database import DB
from ..events.types import EventType, MarketEvent
from ..exec.live_broker import LiveBroker, broker_from_env
from ..exec.margin_check import check_margin
from ..exec.paper_broker import PaperBroker
from ..strategies.base import Signal
from ..portfolio.allocation import is_allocated_symbol, load_target_qty
from ..data.watchlist import is_watchlist_symbol
from ..data.data_policy import DataIntegrityError, require_positive_price
from ..strategies.registry import StrategyRegistry
from ..ops.kill_switch import is_halted, set_halt
from ..ops.daily_pnl import day_drawdown_pct, portfolio_state
from ..ops.budget_gate import can_deploy, consume_rolled_on_deploy, request_budget_increase
from ..rl.action_mask import is_drawdown_halted, max_intraday_drawdown_pct
from ..ops.panic_halt import panic_halt_and_squareoff
from ..ops.cost_gate import min_qty_for_cost_edge
from ..ingest.kite_holdings import real_symbols_held
from ..ops.agent_state import persist_decision
from ..rl.rl_observer import RLObserver
from ..exec.order_fill_handler import paper_fill_event

logger = logging.getLogger("bharatquant.execution")

_HEDGE_ETF = "NIFTYBEES"


class ExecutionEngine:
    def __init__(self, db: DB, registry: StrategyRegistry, router: AgentRouter, bus_publish=None) -> None:
        self.db = db
        self.registry = registry
        self.router = router
        self._bus_publish = bus_publish
        self.costs = CostEngine(slippage_bps=int(os.getenv("SLIPPAGE_BPS", "4")))
        self.paper = PaperBroker(slippage_bps=int(os.getenv("SLIPPAGE_BPS", "4")))
        self.live: Optional[LiveBroker] = broker_from_env()
        self.max_trade = float(os.getenv("MAX_RUPEES_PER_TRADE", "1000"))
        self.max_loss_inr = float(os.getenv("MAX_DAILY_LOSS_RUPEES", "2000"))
        self._rl = RLObserver(db)
        self._deploy_lock = asyncio.Lock()

    def _portfolio(self) -> dict:
        st = portfolio_state(self.db)
        st["halted"] = is_halted(self.db)
        self.router.ctx.positions = load_positions_ctx(self.db)
        return st

    def _record_signal(self, sig: Signal, event: MarketEvent, executed: bool) -> str:
        ts = int(time.time())
        body, _ = build_delivery(
            "strategy.signal",
            {
                "strategy_id": sig.strategy_id,
                "symbol": sig.symbol,
                "action": sig.action,
                "confidence": sig.confidence,
                "executed": executed,
            },
        )
        delivery_id = body["delivery_id"]
        with self.db.tx() as conn:
            conn.execute(
                """
                INSERT INTO strategy_ledger(ts, strategy_id, symbol, event_type, signal, confidence, price, executed, reason, delivery_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ts,
                    sig.strategy_id,
                    sig.symbol,
                    event.type,
                    sig.action,
                    sig.confidence,
                    event.price,
                    1 if executed else 0,
                    sig.reason,
                    delivery_id,
                ),
            )
        if sig.action in ("BUY", "SELL"):
            self._record_meta_row(sig, ts)
        return delivery_id

    def _record_meta_row(self, sig: Signal, ts: int) -> None:
        """Log meta-model training features (calibrated confidence + context) at
        the moment the decision was made, not when it's later labeled — context
        drifts, and the model needs to learn from what was actually known then."""
        try:
            from ..agent.confidence_calibration import calibrate_confidence
            from ..agent.meta_model import record_meta_row

            calibrated = calibrate_confidence(self.db, sig.strategy_id, sig.confidence)
            ctx = self.router.ctx
            record_meta_row(
                self.db,
                ledger_ts=ts,
                strategy_id=sig.strategy_id,
                symbol=sig.symbol,
                raw_confidence=sig.confidence,
                calibrated_confidence=calibrated,
                regime=getattr(ctx, "regime", "SIDEWAYS"),
                india_vix=float(getattr(ctx, "india_vix", 15.0) or 15.0),
                fii_net_cr=float(getattr(ctx, "fii_net_cr", 0.0) or 0.0),
                bandit_weight=self.router._weights.get(sig.strategy_id, 1.0),
            )
        except Exception:
            logger.exception("meta_row_record_failed")

    def _update_strategy_pnl(self, strategy_id: str, pnl_delta: float) -> None:
        ts = int(time.time())
        with self.db.tx() as conn:
            conn.execute(
                """
                INSERT INTO strategy_pnl(strategy_id, realized_pnl, trade_count, updated_ts)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                  realized_pnl = realized_pnl + excluded.realized_pnl,
                  trade_count = trade_count + 1,
                  updated_ts = excluded.updated_ts
                """,
                (strategy_id, pnl_delta, ts),
            )

    def _qty_for(self, symbol: str, ltp: float, port: dict) -> int:
        if ltp <= 0:
            return 0
        sym = symbol.replace("NSE:", "")
        cash = float(port.get("cash", 0))
        use_atr = os.getenv("ATR_SIZING_ENABLED", "true").lower() in ("1", "true", "yes")
        if use_atr:
            from ..portfolio.atr_sizing import atr_qty_for_symbol

            qty = atr_qty_for_symbol(self.db, sym, ltp, cash, self.max_trade)
            if qty > 0:
                return qty
        open_pos = int(port.get("open_positions", 0))
        max_pos = int(os.getenv("MAX_POSITIONS", "8"))
        slots_left = max(1, max_pos - open_pos)
        target_slot = float(os.getenv("TARGET_RUPEES_PER_SLOT", "2500"))
        slots_from_cash = max(1, int(cash * 0.92 / target_slot))
        slots = max(1, min(slots_left, slots_from_cash))
        deployable = cash * 0.92 / slots
        from ..ops.budget_gate import remaining_budget

        cap_rupees = min(self.max_trade, deployable, remaining_budget(self.db))
        from ..ops.vix_controls import vix_sizing_scale

        vix = float(getattr(self.router.ctx, "india_vix", 0) or 0)
        cap_rupees *= vix_sizing_scale(vix)
        planned = load_target_qty(self.db, sym)
        if planned is not None and planned > 0:
            cap_rupees = min(cap_rupees, planned * ltp)
        if cap_rupees < ltp:
            return 0
        min_q = min_qty_for_cost_edge(self.costs, ltp, cap_rupees)
        if min_q <= 0:
            return 0
        qty = max(min_q, int(cap_rupees // ltp))
        return qty if qty * ltp <= cap_rupees + 0.01 else max(0, int(cap_rupees // ltp))

    def _can_buy(self, chosen: Signal, sym: str) -> bool:
        from ..agent.strategy_lifecycle import historical_screen_cleared

        opportunistic = (
            "insider_cluster",
            "bulk_accumulation",
            "pairs_stat_arb",
            "opening_range",
            "affordable_momentum",
            "fast_snapshot",
            "gift_gap",
            "vwap_reversion",
            "connors_ibs",
            "zscore_reversion",
        )
        if chosen.strategy_id in opportunistic:
            return True
        if historical_screen_cleared(self.db, chosen.strategy_id):
            return True
        if chosen.rail.upper() == "MIS":
            return True
        if is_allocated_symbol(self.db, sym):
            return True
        if is_watchlist_symbol(self.db, sym):
            return True
        return False

    def _expected_move_pct(self, sig: Signal) -> float:
        from ..intelligence.corporate_activity import corporate_profit_tilt
        from ..agent.strategy_stats import expected_move_pct_for_strategy

        mult, _ = corporate_profit_tilt(sig.symbol, self.router.ctx)
        return expected_move_pct_for_strategy(self.db, sig.strategy_id, sig.confidence, mult)

    async def _paper_option_hedge(self, chosen: Signal, event: MarketEvent) -> bool:
        """Paper buy protective put when IV strategy fires HEDGE."""
        from ..exec.paper_options import PaperOptionsBroker

        underlying = chosen.symbol.replace("NSE:", "")
        row = self.db._conn.execute(
            """
            SELECT strike, iv, ltp FROM option_iv
            WHERE symbol=? AND option_type='PE' ORDER BY ABS(strike - ?) LIMIT 1
            """,
            (underlying, event.price or 0),
        ).fetchone()
        if not row:
            logger.info("opt_paper_no_chain", extra={"underlying": underlying})
            persist_decision(self.db, {
                "action": "OPT_SKIP",
                "symbol": underlying,
                "reason": "no_option_chain_data",
            })
            return False
        qty = 1
        broker = PaperOptionsBroker()
        result = broker.buy(
            self.db,
            underlying=underlying,
            strike=float(row["strike"]),
            option_type="PE",
            qty=qty,
            ltp=float(row["ltp"] or 50),
            expiry="PAPER",
            reason=chosen.reason,
        )
        persist_decision(self.db, {
            "action": "OPT_BUY",
            "symbol": result.get("symbol"),
            "underlying": underlying,
            "executed": True,
            "strategy": chosen.strategy_id,
        })
        return bool(result.get("ok"))


    async def _train_after_trade(self) -> None:
        if os.getenv("RL_TRAIN_ON_TRADE", "true").lower() not in ("1", "true", "yes"):
            return
        try:
            from ..ops.gcs_store import sync_rl_model
            from ..rl.training_guardrails import guarded_train_and_promote

            result = await asyncio.to_thread(
                guarded_train_and_promote,
                self.db,
                os.getenv("RL_MODEL_DIR", "models/rl"),
                os.getenv("RL_ACTIVE_VERSION", "ppo_v1"),
                skip_shadow=True,
            )
            if result.get("promoted") and result.get("train", {}).get("status") == "ok":
                if self.router._rl_agent:
                    self.router._rl_agent.reload()
                await asyncio.to_thread(
                    sync_rl_model,
                    os.getenv("RL_MODEL_DIR", "models/rl"),
                    os.getenv("RL_ACTIVE_VERSION", "ppo_v1"),
                )
            logger.info("rl_train_on_trade", extra=result)
        except Exception:
            logger.exception("rl_train_on_trade_failed")

    async def on_event(self, event: MarketEvent) -> None:
        if is_halted(self.db):
            return
        if event.symbol and event.price > 0:
            self.router.ctx.last_ltp[event.symbol] = float(event.price)
        port = self._portfolio()
        dd_pct = day_drawdown_pct(self.db, port["total_equity"])
        if is_drawdown_halted(self.db, port["total_equity"]):
            if not is_halted(self.db):
                panic_halt_and_squareoff(
                    self.db,
                    reason=f"intraday_drawdown_{dd_pct:.1f}pct",
                )
                await send_telegram(
                    f"HALT intraday drawdown {dd_pct:.1f}% (limit {max_intraday_drawdown_pct():.0f}%) — positions flattened"
                )
                logger.warning("intraday_drawdown_halt", extra={"drawdown_pct": dd_pct})
            return
        if port.get("day_loss_rupees", 0) >= self.max_loss_inr:
            set_halt(self.db, reason="daily_loss_rupees_gate")
            await send_telegram(f"HALT daily loss ₹{port['day_loss_rupees']:.0f}")
            logger.warning("daily_loss_halt", extra={"loss_inr": port["day_loss_rupees"]})
            return
        signals: list[Signal] = []
        chosen: Optional[Signal] = None
        if event.type == EventType.FAST_SNAPSHOT:
            logger.info(
                "fast_snapshot_execute",
                extra={"symbol": event.symbol, "price": event.price, "reason": (event.payload or {}).get("reason")},
            )
            pl = event.payload or {}
            chosen = Signal(
                pl.get("strategy_id", "fast_snapshot"),
                event.symbol or "",
                pl.get("action", "BUY"),
                pl.get("rail", "MIS"),
                float(pl.get("confidence", 0.75)),
                pl.get("reason", "holistic_snapshot"),
            )
        else:
            signals = await self.registry.dispatch(event, self.router.ctx)
            if not signals:
                return
            chosen = self.router.fuse(
                signals,
                event_price=float(event.price or 0),
                event_symbol=event.symbol or "",
            )
            if not chosen:
                for s in signals:
                    self._record_signal(s, event, False)
                    self.router.maybe_shadow(s, event.price, False)
                persist_decision(self.db, {
                    "action": "PASS",
                    "reason": "no_fused_signal",
                    "candidates": len(signals),
                    "event": str(event.type),
                })
                return
            for s in signals:
                if s.strategy_id == chosen.strategy_id and s.symbol == chosen.symbol and s.action == chosen.action:
                    continue
                self._record_signal(s, event, False)
                self.router.maybe_shadow(s, event.price, False)
        if not chosen:
            return
        from ..ops.vix_controls import llm_bearish_veto_threshold

        llm_bias = float(getattr(self.router.ctx, "llm_bias", 0) or 0)
        if chosen.action == "BUY" and llm_bias <= llm_bearish_veto_threshold():
            reason = f"llm_bearish_veto bias={llm_bias:+.2f}"
            logger.info("llm_bearish_veto", extra={"bias": llm_bias, "symbol": chosen.symbol})
            self._record_signal(chosen, event, False)
            self._rl.record_skip(self.router.ctx, chosen, reason=reason)
            persist_decision(self.db, {
                "action": "VETO",
                "strategy": chosen.strategy_id,
                "symbol": chosen.symbol,
                "signal": chosen.action,
                "reason": reason,
            })
            return
        from ..ops.slumber_mode import is_slumbering

        if chosen.action == "BUY" and is_slumbering(self.db):
            reason = "slumber_mode_active"
            logger.info("slumber_veto", extra={"symbol": chosen.symbol})
            self._record_signal(chosen, event, False)
            self._rl.record_skip(self.router.ctx, chosen, reason=reason)
            persist_decision(self.db, {
                "action": "VETO",
                "strategy": chosen.strategy_id,
                "symbol": chosen.symbol,
                "signal": chosen.action,
                "reason": reason,
            })
            return
        from ..ops.session_state import entries_allowed

        if chosen.action == "BUY" and not entries_allowed():
            reason = "session_not_open"
            logger.info("session_entry_veto", extra={"symbol": chosen.symbol})
            self._record_signal(chosen, event, False)
            self._rl.record_skip(self.router.ctx, chosen, reason=reason)
            persist_decision(self.db, {
                "action": "VETO",
                "strategy": chosen.strategy_id,
                "symbol": chosen.symbol,
                "signal": chosen.action,
                "reason": reason,
            })
            return
        from ..ops.execution_cooldown import can_place_order

        if chosen.action in ("BUY", "SELL"):
            ok_cd, wait_sec = can_place_order(self.db)
            if not ok_cd:
                logger.info("execution_cooldown", extra={"wait_sec": wait_sec, "symbol": chosen.symbol})
                self._record_signal(chosen, event, False)
                self._rl.record_skip(self.router.ctx, chosen, reason="execution_cooldown")
                return
        sym = chosen.symbol.replace("NSE:", "")
        ok, reason = self.router.risk_veto(chosen, port)
        self._rl.snapshot_before(self.router.ctx, chosen, score=chosen.confidence)
        if not ok and chosen.action == "BUY":
            logger.info("risk_veto", extra={"reason": reason, "symbol": chosen.symbol})
            self._record_signal(chosen, event, False)
            self.router.maybe_shadow(chosen, event.price, False)
            self._rl.record_skip(self.router.ctx, chosen, reason=reason)
            persist_decision(self.db, {
                "action": "VETO",
                "strategy": chosen.strategy_id,
                "symbol": chosen.symbol,
                "signal": chosen.action,
                "reason": reason,
            })
            return
        if chosen.action == "HEDGE":
            opt_paper = os.getenv("OPTIONS_PAPER_ENABLED", "true").lower() in ("1", "true", "yes")
            if chosen.rail.upper() == "OPT" and opt_paper:
                executed = await self._paper_option_hedge(chosen, event)
                self._record_signal(chosen, event, executed)
                return
            chosen = Signal(
                chosen.strategy_id,
                _HEDGE_ETF,
                "BUY",
                "CNC",
                chosen.confidence,
                f"{chosen.reason}->defensive_etf",
                meta=chosen.meta,
            )
        if chosen.action == "BUY" and not self._can_buy(chosen, chosen.symbol):
            logger.info("allocation_veto", extra={"symbol": chosen.symbol})
            self._record_signal(chosen, event, False)
            self._rl.record_skip(self.router.ctx, chosen, reason="allocation_veto")
            return
        if chosen.action == "BUY" and is_excluded(self.db, chosen.symbol):
            self._record_signal(chosen, event, False)
            self._rl.record_skip(self.router.ctx, chosen, reason="asm_gsm")
            return
        try:
            ltp = require_positive_price(event.price, chosen.symbol)
        except DataIntegrityError:
            if chosen.symbol.replace("NSE:", "") == _HEDGE_ETF:
                row = self.db._conn.execute(
                    "SELECT ltp FROM tick_log WHERE symbol=? ORDER BY ts DESC LIMIT 1",
                    (_HEDGE_ETF,),
                ).fetchone()
                ltp = float(row["ltp"]) if row else 0.0
                if ltp <= 0:
                    logger.error("hedge_etf_ltp_missing")
                    self._record_signal(chosen, event, False)
                    return
            else:
                logger.error("ltp_missing", extra={"symbol": chosen.symbol})
                self._record_signal(chosen, event, False)
                return
        qty = self._qty_for(chosen.symbol, ltp, port)
        if chosen.action == "BUY" and qty <= 0:
            cash = float(port.get("cash", 0))
            from ..ops.budget_gate import remaining_budget

            rem = remaining_budget(self.db)
            if rem < ltp:
                reason = f"daily_budget_insufficient ltp=₹{ltp:.0f} remaining=₹{rem:.0f}"
            elif cash < ltp:
                reason = f"insufficient_cash ltp=₹{ltp:.0f} cash=₹{cash:.0f}"
            else:
                reason = f"affordability_veto ltp=₹{ltp:.0f} deploy_cap=₹{min(self.max_trade, rem):.0f}"
            logger.info("affordability_veto", extra={"symbol": chosen.symbol, "ltp": ltp, "cash": cash, "reason": reason})
            self._record_signal(chosen, event, False)
            self._rl.record_skip(self.router.ctx, chosen, reason=reason)
            persist_decision(self.db, {
                "action": "VETO",
                "strategy": chosen.strategy_id,
                "symbol": chosen.symbol,
                "signal": chosen.action,
                "reason": reason,
            })
            return
        if chosen.action == "BUY" and qty > 0:
            est_cost = qty * ltp
            ok_budget, budget_reason = can_deploy(self.db, est_cost)
            if not ok_budget:
                if "daily_budget_cap" in budget_reason or budget_reason == "budget_exceeded_pending_approval":
                    from ..ops.budget_gate import approved_daily_max

                    request_budget_increase(
                        self.db,
                        approved_daily_max(self.db) + est_cost,
                        f"{chosen.strategy_id}:{sym} needs ₹{est_cost:.0f}",
                    )
                logger.info("budget_veto", extra={"reason": budget_reason, "est": est_cost})
                self._record_signal(chosen, event, False)
                self._rl.record_skip(self.router.ctx, chosen, reason=budget_reason)
                persist_decision(self.db, {
                    "action": "VETO",
                    "strategy": chosen.strategy_id,
                    "symbol": chosen.symbol,
                    "signal": chosen.action,
                    "reason": budget_reason,
                })
                return
            held_real = real_symbols_held(self.db)
            if sym in held_real and chosen.rail.upper() == "CNC":
                logger.info("real_holdings_skip", extra={"symbol": sym})
                self._record_signal(chosen, event, False)
                self._rl.record_skip(self.router.ctx, chosen, reason="already_in_real_portfolio")
                persist_decision(self.db, {
                    "action": "VETO",
                    "strategy": chosen.strategy_id,
                    "symbol": chosen.symbol,
                    "signal": chosen.action,
                    "reason": "already_in_real_portfolio",
                })
                return
            min_move = self.costs.min_profit_move_pct(qty, ltp)
            expected = self._expected_move_pct(chosen)
            if expected < min_move:
                logger.info(
                    "cost_edge_veto",
                    extra={"symbol": chosen.symbol, "expected": expected, "min_move": min_move},
                )
                self._record_signal(chosen, event, False)
                self._rl.record_skip(self.router.ctx, chosen, reason="cost_edge_too_thin")
                persist_decision(self.db, {
                    "action": "VETO",
                    "strategy": chosen.strategy_id,
                    "symbol": chosen.symbol,
                    "signal": chosen.action,
                    "reason": f"cost_edge expected={expected:.2f}% need={min_move:.2f}%",
                })
                return
        ts = int(time.time())
        realized_pnl = 0.0
        cost_basis = 0.0
        if chosen.action == "BUY":
            async with self._deploy_lock:
                # Authoritative budget re-check — must happen inside the lock, atomic with
                # the record_trade write below. The pre-lock can_deploy() above is only a
                # cheap early-reject hint; without this re-check, concurrent handlers can
                # both pass the pre-lock check before either has recorded a trade (TOCTOU),
                # overspending the daily cap.
                fees_est = self.costs.compute_trade_costs(chosen.symbol, qty, ltp, "BUY")
                total_cost_est = ltp * qty + fees_est
                ok_budget2, budget_reason2 = can_deploy(self.db, total_cost_est)
                if not ok_budget2:
                    logger.info("budget_veto_in_lock", extra={"reason": budget_reason2, "est": total_cost_est})
                    self._record_signal(chosen, event, False)
                    self._rl.record_skip(self.router.ctx, chosen, reason=budget_reason2)
                    persist_decision(self.db, {
                        "action": "VETO",
                        "strategy": chosen.strategy_id,
                        "symbol": chosen.symbol,
                        "signal": chosen.action,
                        "reason": budget_reason2,
                    })
                    return
                cash = float(port.get("cash", 0))
                ok_m, m_reason = check_margin(
                    symbol=sym,
                    qty=qty,
                    price=ltp,
                    rail=chosen.rail,
                    available_cash=cash,
                    kite=self.live._kite if self.live else None,
                )
                if not ok_m:
                    logger.info("margin_veto", extra={"reason": m_reason})
                    self._record_signal(chosen, event, False)
                    self._rl.record_skip(self.router.ctx, chosen, reason=m_reason)
                    return
                if self.live and os.getenv("TRADING_MODE") == "live":
                    from ..exec.pending_orders import record_pending
                    from ..exec.broker_sl import place_sl_m
                    from ..ops.execution_cooldown import mark_order_placed

                    oid = await self.live.place_async(chosen, ltp, qty)
                    executed = oid is not None
                    exec_px = ltp
                    order_id = str(oid) if oid else None
                    if executed and order_id:
                        record_pending(
                            self.db,
                            order_id=order_id,
                            symbol=sym,
                            side="BUY",
                            qty=qty,
                            price=ltp,
                            rail=chosen.rail,
                            strategy_id=chosen.strategy_id,
                            reason=chosen.reason,
                        )
                        mark_order_placed(self.db)
                        place_sl_m(self.live._kite, chosen, qty, ltp)
                else:
                    exec_px = self.paper.buy(chosen.symbol, qty, ltp)
                    executed = True
                    order_id = f"PAPER-B-{ts}"
                if executed:
                    if self.live and os.getenv("TRADING_MODE") == "live" and order_id:
                        pass  # positions updated on ORDER_FILL via settle_pending_fill
                    else:
                        fees = self.costs.compute_trade_costs(chosen.symbol, qty, exec_px, "BUY", order_id=order_id)
                        cost = exec_px * qty + fees
                        tid = self.db.record_trade(
                            ts, sym, "BUY", qty, exec_px, cost, chosen.reason, fees, "NA", order_id=order_id
                        )
                        self.db.add_cash(ts, -cost, f"buy:{sym}")
                        consume_rolled_on_deploy(self.db, cost)
                        from ..ops.slippage_parity import record_slippage_pair

                        record_slippage_pair(
                            self.db,
                            symbol=sym,
                            side="BUY",
                            predicted_price=ltp,
                            actual_price=exec_px,
                            qty=qty,
                            strategy_id=chosen.strategy_id,
                            source=os.getenv("TRADING_MODE", "paper"),
                        )
                        open_lot(self.db, sym, qty, exec_px, ts, chosen.rail, tid)
                        # Refresh — not just re-init-once-at-startup. ctx.positions is
                        # read by stop_loss_guard, affordable_momentum, iv_premium_sell,
                        # signal_combiner, and router.risk_veto for live decisions; a
                        # stale copy after a trade is exactly the class of bug reported
                        # independently by another builder ("agent sat idle 4 hours
                        # thinking it was maxed out when positions were already closed").
                        self.router.ctx.positions = load_positions_ctx(self.db)
                        from ..ops.execution_cooldown import mark_order_placed

                        mark_order_placed(self.db)
                        from ..agent.strategy_lifecycle import record_probation_trade

                        record_probation_trade(self.db, chosen.strategy_id)
                        if self._bus_publish and order_id:
                            await self._bus_publish(paper_fill_event(sym, "BUY", qty, exec_px, order_id))
                        await self._train_after_trade()
        elif chosen.action == "SELL":
            cur = self.db._conn.execute("SELECT qty FROM positions WHERE symbol=?", (sym,))
            row = cur.fetchone()
            if not row or int(row["qty"]) <= 0:
                self._record_signal(chosen, event, False)
                return
            qty = int(row["qty"])
            if self.live and os.getenv("TRADING_MODE") == "live":
                from ..exec.pending_orders import record_pending
                from ..ops.execution_cooldown import mark_order_placed

                oid = await self.live.place_async(chosen, ltp, qty)
                executed = oid is not None
                exec_px = ltp
                order_id = str(oid) if oid else None
                if executed and order_id:
                    record_pending(
                        self.db,
                        order_id=order_id,
                        symbol=sym,
                        side="SELL",
                        qty=qty,
                        price=ltp,
                        rail=chosen.rail,
                        strategy_id=chosen.strategy_id,
                        reason=chosen.reason,
                    )
                    mark_order_placed(self.db)
            else:
                exec_px = self.paper.sell(chosen.symbol, qty, ltp)
                executed = True
                order_id = f"PAPER-S-{ts}"
            if executed:
                if self.live and os.getenv("TRADING_MODE") == "live" and order_id:
                    pass
                else:
                    fees = self.costs.compute_trade_costs(chosen.symbol, qty, exec_px, "SELL", order_id=order_id)
                    pos_row = self.db._conn.execute(
                        "SELECT qty, avg_price FROM positions WHERE symbol=?", (sym,)
                    ).fetchone()
                    cost_basis = float(pos_row["avg_price"]) * qty if pos_row else exec_px * qty
                    fills, tax_class = close_lots_fifo(self.db, sym, qty, exec_px, ts, self.costs)
                    proceeds = exec_px * qty - fees
                    realized_pnl = sum(f.pnl for f in fills) - fees
                    sell_tid = self.db.record_trade(
                        ts, sym, "SELL", qty, exec_px, proceeds, chosen.reason, fees, tax_class, order_id=order_id
                    )
                    self.db.add_cash(ts, proceeds, f"sell:{sym}")
                    self._update_strategy_pnl(chosen.strategy_id, realized_pnl)
                    self.router.ctx.positions = load_positions_ctx(self.db)
                    from ..ops.symbol_session_cooldown import record_losing_close
                    from ..ops.loss_ledger import record_closed_loss
                    from ..ops.slippage_parity import record_slippage_pair

                    slip_inr = (exec_px - ltp) * qty
                    slip_bps = (exec_px - ltp) / ltp * 10_000 if ltp > 0 else 0.0
                    record_slippage_pair(
                        self.db,
                        symbol=sym,
                        side="SELL",
                        predicted_price=ltp,
                        actual_price=exec_px,
                        qty=qty,
                        strategy_id=chosen.strategy_id,
                        source=os.getenv("TRADING_MODE", "paper"),
                    )
                    if realized_pnl < 0:
                        record_losing_close(self.db, sym, realized_pnl, chosen.strategy_id)
                        cost_drag = abs(slip_inr) / max(1.0, abs(realized_pnl)) * 100.0
                        signal_fail = max(0.0, 100.0 - cost_drag)
                        record_closed_loss(
                            self.db,
                            trade_id=sell_tid,
                            symbol=sym,
                            strategy_id=chosen.strategy_id,
                            pnl_inr=realized_pnl,
                            regime_entry=str(getattr(self.router.ctx, "regime", "NEUTRAL")),
                            regime_exit=str(getattr(self.router.ctx, "regime", "NEUTRAL")),
                            stop_designed="stop" in chosen.reason.lower(),
                            stop_slipped=abs(slip_bps) > 20,
                            slippage_inr=slip_inr,
                            slippage_bps=slip_bps,
                            signal_failure_pct=signal_fail,
                            cost_drag_pct=cost_drag,
                        )
                    self.router.record_return(realized_pnl / max(1.0, port.get("total_equity", 1)))
                    from ..ops.execution_cooldown import mark_order_placed

                    mark_order_placed(self.db)
                    if self._bus_publish and order_id:
                        await self._bus_publish(paper_fill_event(sym, "SELL", qty, exec_px, order_id))
                    await self._train_after_trade()
        else:
            executed = False
        self._record_signal(chosen, event, executed)
        self._rl.record_outcome(
            self.router.ctx,
            chosen,
            executed=executed,
            daily_return=float(port.get("day_loss_rupees", 0)) / max(1.0, port.get("total_equity", 1)),
            realized_pnl=realized_pnl,
            cost_basis=cost_basis,
        )
        persist_decision(self.db, {
            "action": chosen.action if executed else f"{chosen.action}_skipped",
            "strategy": chosen.strategy_id,
            "symbol": chosen.symbol,
            "confidence": chosen.confidence,
            "executed": executed,
            "regime": self.router.ctx.regime,
        })
        if chosen.action in ("BUY", "SELL"):
            await publish_strategy_alert(
                chosen.strategy_id,
                chosen.symbol,
                chosen.action,
                chosen.confidence,
                chosen.reason,
            )

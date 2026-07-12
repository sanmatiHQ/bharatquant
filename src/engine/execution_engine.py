"""Event-driven execution handler — paper or live."""
from __future__ import annotations

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
from ..data.data_policy import DataIntegrityError, require_positive_price
from ..strategies.registry import StrategyRegistry
from ..ops.kill_switch import is_halted, set_halt
from ..ops.daily_pnl import portfolio_state
from ..ops.agent_state import persist_decision
from ..rl.rl_observer import RLObserver
from ..exec.order_fill_handler import paper_fill_event

logger = logging.getLogger("bharatquant.execution")


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
        return delivery_id

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

    def _qty_for(self, symbol: str, ltp: float) -> int:
        if ltp <= 0:
            return 0
        sym = symbol.replace("NSE:", "")
        planned = load_target_qty(self.db, sym)
        if planned is not None and planned > 0:
            cap = max(1, int(self.max_trade // ltp))
            return min(planned, cap)
        return max(1, int(self.max_trade // ltp))

    async def on_event(self, event: MarketEvent) -> None:
        if is_halted(self.db):
            return
        port = self._portfolio()
        if port.get("day_loss_rupees", 0) >= self.max_loss_inr:
            set_halt(self.db, reason="daily_loss_rupees_gate")
            await send_telegram(f"HALT daily loss ₹{port['day_loss_rupees']:.0f}")
            logger.warning("daily_loss_halt", extra={"loss_inr": port["day_loss_rupees"]})
            return
        signals = await self.registry.dispatch(event, self.router.ctx)
        if not signals:
            return
        chosen = self.router.fuse(signals)
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
        ok, reason = self.router.risk_veto(chosen, port)
        self._rl.snapshot_before(self.router.ctx, chosen, score=chosen.confidence)
        if not ok and chosen.action == "BUY":
            logger.info("risk_veto", extra={"reason": reason, "symbol": chosen.symbol})
            self._record_signal(chosen, event, False)
            self.router.maybe_shadow(chosen, event.price, False)
            persist_decision(self.db, {
                "action": "VETO",
                "strategy": chosen.strategy_id,
                "symbol": chosen.symbol,
                "signal": chosen.action,
                "reason": reason,
            })
            return
        if chosen.action == "BUY" and not is_allocated_symbol(self.db, chosen.symbol):
            if chosen.strategy_id not in ("insider_cluster", "bulk_accumulation", "pairs_stat_arb"):
                logger.info("allocation_veto", extra={"symbol": chosen.symbol})
                self._record_signal(chosen, event, False)
                return
        if chosen.action == "BUY" and is_excluded(self.db, chosen.symbol):
            self._record_signal(chosen, event, False)
            return
        if chosen.action == "HEDGE":
            self._record_signal(chosen, event, False)
            return
        try:
            ltp = require_positive_price(event.price, chosen.symbol)
        except DataIntegrityError:
            logger.error("ltp_missing", extra={"symbol": chosen.symbol})
            self._record_signal(chosen, event, False)
            return
        qty = self._qty_for(chosen.symbol, ltp)
        ts = int(time.time())
        sym = chosen.symbol.replace("NSE:", "")
        if chosen.action == "BUY":
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
                return
            if self.live and os.getenv("TRADING_MODE") == "live":
                oid = self.live.place(chosen, ltp, qty)
                executed = oid is not None
                exec_px = ltp
                order_id = str(oid) if oid else None
            else:
                exec_px = self.paper.buy(chosen.symbol, qty, ltp)
                executed = True
                order_id = f"PAPER-B-{ts}"
            if executed:
                fees = self.costs.compute_trade_costs(chosen.symbol, qty, exec_px, "BUY", order_id=order_id)
                cost = exec_px * qty + fees
                tid = self.db.record_trade(
                    ts, sym, "BUY", qty, exec_px, cost, chosen.reason, fees, "NA", order_id=order_id
                )
                self.db.add_cash(ts, -cost, f"buy:{sym}")
                open_lot(self.db, sym, qty, exec_px, ts, chosen.rail, tid)
                if self._bus_publish and order_id:
                    await self._bus_publish(paper_fill_event(sym, "BUY", qty, exec_px, order_id))
        elif chosen.action == "SELL":
            cur = self.db._conn.execute("SELECT qty FROM positions WHERE symbol=?", (sym,))
            row = cur.fetchone()
            if not row or int(row["qty"]) <= 0:
                self._record_signal(chosen, event, False)
                return
            qty = int(row["qty"])
            if self.live and os.getenv("TRADING_MODE") == "live":
                oid = self.live.place(chosen, ltp, qty)
                executed = oid is not None
                exec_px = ltp
                order_id = str(oid) if oid else None
            else:
                exec_px = self.paper.sell(chosen.symbol, qty, ltp)
                executed = True
                order_id = f"PAPER-S-{ts}"
            if executed:
                fees = self.costs.compute_trade_costs(chosen.symbol, qty, exec_px, "SELL", order_id=order_id)
                fills, tax_class = close_lots_fifo(self.db, sym, qty, exec_px, ts, self.costs)
                proceeds = exec_px * qty - fees
                realized = sum(f.pnl for f in fills) - fees
                self.db.record_trade(
                    ts, sym, "SELL", qty, exec_px, proceeds, chosen.reason, fees, tax_class, order_id=order_id
                )
                self.db.add_cash(ts, proceeds, f"sell:{sym}")
                self._update_strategy_pnl(chosen.strategy_id, realized)
                self.router.record_return(realized / max(1.0, port.get("total_equity", 1)))
                if self._bus_publish and order_id:
                    await self._bus_publish(paper_fill_event(sym, "SELL", qty, exec_px, order_id))
        else:
            executed = False
        self._record_signal(chosen, event, executed)
        self._rl.record_outcome(
            self.router.ctx,
            chosen,
            executed=executed,
            daily_return=float(port.get("day_loss_rupees", 0)) / max(1.0, port.get("total_equity", 1)),
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

"""Position monitor — TICK → STOP_BREACH / TAKE_PROFIT events (no cron)."""
from __future__ import annotations

import logging
import os
from typing import Callable, Dict

from ..db.database import DB
from ..events.types import EventType, MarketEvent
from ..risk.risk_engine import RiskEngine, risk_config_from_env

logger = logging.getLogger("bharatquant.position_monitor")


class PositionMonitor:
    def __init__(self, db: DB, publish: Callable, risk: RiskEngine | None = None) -> None:
        self.db = db
        self.publish = publish
        self.risk = risk or RiskEngine(risk_config_from_env())
        self._peak_price: Dict[str, float] = {}
        self._india_vix: float = 0.0

    def refresh_vix(self) -> None:
        from ..ops.vix_controls import vix_from_db

        self._india_vix = vix_from_db(self.db)

    async def on_tick(self, event: MarketEvent) -> None:
        sym = event.symbol
        if not sym or event.price <= 0:
            return
        cur = self.db._conn.execute(
            "SELECT symbol, qty, avg_price, last_price, open_ts, rail FROM positions WHERE symbol=?",
            (sym,),
        )
        row = cur.fetchone()
        if not row:
            return
        self.db._conn.execute(
            "UPDATE positions SET last_price=? WHERE symbol=?",
            (event.price, sym),
        )
        self.db._conn.commit()

        peak = self._peak_price.get(sym, float(row["last_price"]))
        peak = max(peak, event.price)
        self._peak_price[sym] = peak

        state = {
            "avg_price": float(row["avg_price"]),
            "last_price": event.price,
            "open_ts": int(row["open_ts"]),
            "peak_price": peak,
            "rail": str(row["rail"] or "CNC"),
        }
        should_exit, reason = self.risk.should_exit(state, peak_price=peak, india_vix=self._india_vix)
        if not should_exit:
            return

        ev_type = EventType.TAKE_PROFIT if reason.startswith(("take_profit", "trailing_stop", "max_hold")) else EventType.STOP_BREACH
        await self.publish(
            MarketEvent(
                type=ev_type,
                symbol=sym,
                price=event.price,
                payload={"avg_price": state["avg_price"], "rail": state["rail"], "reason": reason},
            )
        )
        logger.info("position_exit_signal", extra={"symbol": sym, "reason": reason, "event": str(ev_type)})

    async def on_session_close(self, event: MarketEvent) -> None:
        """Square off MIS positions on SESSION_CLOSE."""
        cur = self.db._conn.execute(
            "SELECT symbol, qty, last_price, rail FROM positions WHERE qty > 0"
        )
        for row in cur.fetchall():
            rail = str(row["rail"] or "CNC").upper()
            if rail != "MIS":
                continue
            sym = row["symbol"]
            self._peak_price.pop(sym, None)
            await self.publish(
                MarketEvent(
                    type=EventType.STOP_BREACH,
                    symbol=sym,
                    price=float(row["last_price"]),
                    payload={"rail": "MIS", "reason": "session_close_squareoff"},
                )
            )

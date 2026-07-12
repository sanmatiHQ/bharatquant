"""Position monitor — TICK → STOP_BREACH events (no cron)."""
from __future__ import annotations

import logging
from typing import Callable

from ..db.database import DB
from ..events.types import EventType, MarketEvent
from ..risk.risk_engine import RiskConfig, RiskEngine

logger = logging.getLogger("bharatquant.position_monitor")


class PositionMonitor:
    def __init__(self, db: DB, publish: Callable, risk: RiskEngine | None = None) -> None:
        self.db = db
        self.publish = publish
        self.risk = risk or RiskEngine(
            RiskConfig(
                stop_loss_percent=4.0,
                max_daily_loss_percent=2.0,
                max_daily_loss_rupees=2000.0,
                max_positions=5,
            )
        )

    async def on_tick(self, event: MarketEvent) -> None:
        sym = event.symbol
        if not sym or event.price <= 0:
            return
        cur = self.db._conn.execute(
            "SELECT symbol, qty, avg_price, last_price FROM positions WHERE symbol=?",
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
        state = {
            "avg_price": float(row["avg_price"]),
            "last_price": event.price,
        }
        if self.risk.should_exit(state):
            await self.publish(
                MarketEvent(
                    type=EventType.STOP_BREACH,
                    symbol=sym,
                    price=event.price,
                    payload={"avg_price": state["avg_price"]},
                )
            )

    async def on_session_close(self, event: MarketEvent) -> None:
        """Square off MIS positions on SESSION_CLOSE."""
        cur = self.db._conn.execute(
            "SELECT symbol, qty, last_price, rail FROM positions WHERE qty > 0"
        )
        for row in cur.fetchall():
            rail = str(row["rail"] or "CNC").upper()
            if rail != "MIS":
                continue
            await self.publish(
                MarketEvent(
                    type=EventType.STOP_BREACH,
                    symbol=row["symbol"],
                    price=float(row["last_price"]),
                    payload={"rail": "MIS", "reason": "session_close_squareoff"},
                )
            )

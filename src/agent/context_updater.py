"""Centralize ingest events → MarketContext (no LLM)."""
from __future__ import annotations

import logging
from typing import Callable

from ..events.types import EventType, MarketEvent
from ..strategies.base import MarketContext

logger = logging.getLogger("bharatquant.context")


class ContextUpdater:
    def __init__(self, ctx: MarketContext) -> None:
        self.ctx = ctx

    async def on_event(self, event: MarketEvent) -> None:
        p = event.payload or {}
        if event.type == EventType.FII_DII_UPDATE:
            self.ctx.fii_net_cr = float(p.get("fii_net", 0))
            self.ctx.dii_net_cr = float(p.get("dii_net", 0))
            fn = self.ctx.fii_net_cr
            if fn < -500:
                self.ctx.regime = "RISK_OFF"
            elif fn > 500:
                self.ctx.regime = "RISK_ON"
            else:
                from ..agent.regime_classifier import classify_regime

                rs = classify_regime([fn / 10000.0], self.ctx.india_vix)
                self.ctx.regime = rs.label if rs.label != "SIDEWAYS" else "NEUTRAL"
            logger.info(
                "context_fii",
                extra={"fii_net": fn, "regime": self.ctx.regime},
            )
        elif event.type == EventType.GIFT_TICK:
            self.ctx.gift_nifty_change_pct = float(p.get("change_pct", 0))
        elif event.type == EventType.IV_UPDATE:
            self.ctx.india_vix = float(p.get("vix", p.get("india_vix", 0)))
        elif event.type == EventType.PREOPEN_PRICE and event.symbol:
            self.ctx.orb_high[event.symbol] = float(p.get("iep", event.price) or event.price)
            self.ctx.orb_low[event.symbol] = float(p.get("low", event.price) or event.price)
        elif event.type == EventType.TICK and event.symbol:
            sym = event.symbol.replace("NSE:", "")
            if sym not in self.ctx.session_vwap and event.price > 0:
                self.ctx.session_vwap[sym] = event.price

    def subscribe(self, bus) -> None:
        types = (
            EventType.FII_DII_UPDATE,
            EventType.GIFT_TICK,
            EventType.IV_UPDATE,
            EventType.PREOPEN_PRICE,
            EventType.TICK,
        )
        for t in types:
            bus.subscribe(t, self.on_event)


def make_context_handler(ctx: MarketContext) -> Callable:
    updater = ContextUpdater(ctx)
    return updater.on_event

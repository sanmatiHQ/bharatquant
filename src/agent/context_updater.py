"""Centralize ingest events → unified MarketContext state vector."""
from __future__ import annotations

import logging
import os
from typing import Callable

from ..events.types import EventType, MarketEvent
from ..strategies.base import MarketContext

logger = logging.getLogger("bharatquant.context")


class ContextUpdater:
    def __init__(self, ctx: MarketContext, db=None) -> None:
        self.ctx = ctx
        self.db = db

    async def on_event(self, event: MarketEvent) -> None:
        p = event.payload or {}
        if event.type == EventType.FII_DII_UPDATE:
            self.ctx.fii_net_cr = float(p.get("fii_net", 0))
            self.ctx.dii_net_cr = float(p.get("dii_net", 0))
            fn = self.ctx.fii_net_cr
            paper_learn = os.getenv("TRADING_PHASE", "paper_learn") == "paper_learn"
            if fn < -500 and not paper_learn:
                self.ctx.regime = "RISK_OFF"
            elif fn > 500:
                self.ctx.regime = "RISK_ON"
            elif not paper_learn:
                from ..agent.regime_classifier import classify_regime

                rs = classify_regime([fn / 10000.0], self.ctx.india_vix)
                self.ctx.regime = rs.label if rs.label != "SIDEWAYS" else "NEUTRAL"
            logger.info("context_fii", extra={"fii_net": fn, "regime": self.ctx.regime})
        elif event.type == EventType.GIFT_TICK:
            self.ctx.gift_nifty_change_pct = float(p.get("change_pct", 0))
        elif event.type == EventType.GIFT_SESSION_CHANGE:
            self.ctx.us_sp_change_pct = float(p.get("us_sp", 0))
            self.ctx.crude_change_pct = float(p.get("crude", 0))
            self.ctx.usd_inr_change_pct = float(p.get("usd_inr", 0))
            if p.get("us_vix_chg") is not None:
                self.ctx.us_vix_chg = float(p["us_vix_chg"])
            if p.get("nikkei_chg") is not None:
                self.ctx.nikkei_chg = float(p["nikkei_chg"])
            if p.get("hang_seng_chg") is not None:
                self.ctx.hang_seng_chg = float(p["hang_seng_chg"])
            if p.get("india_vix"):
                self.ctx.india_vix = float(p["india_vix"])
        elif event.type == EventType.LLM_BIAS_UPDATE:
            self.ctx.llm_bias = float(p.get("llm_bias", p.get("llm_sentiment", 0)) or 0)
            sectors = p.get("sectors") or {}
            if isinstance(sectors, dict):
                self.ctx.llm_sector_bias = {str(k): float(v) for k, v in sectors.items()}
            logger.info("context_llm_bias", extra={"bias": self.ctx.llm_bias})
        elif event.type == EventType.FUTURES_OI_UPDATE:
            self.ctx.futures_oi_chg = float(p.get("oi_change_pct", 0) or 0)
        elif event.type == EventType.IV_UPDATE:
            self.ctx.india_vix = float(p.get("vix", p.get("india_vix", 0)))
        elif event.type == EventType.PREOPEN_PRICE and event.symbol:
            sym = event.symbol.replace("NSE:", "")
            iep = float(p.get("iep", event.price) or event.price)
            self.ctx.orb_high[sym] = iep
            self.ctx.orb_low[sym] = float(p.get("low", event.price) or event.price)
            if iep > 0:
                self.ctx.session_open[sym] = iep
        elif event.type == EventType.TICK and event.symbol:
            sym = event.symbol.replace("NSE:", "")
            if sym not in self.ctx.session_open and event.price > 0:
                ref = self.ctx.orb_low.get(sym) or self.ctx.orb_high.get(sym)
                self.ctx.session_open[sym] = float(ref) if ref else event.price
            if sym not in self.ctx.session_vwap and event.price > 0:
                self.ctx.session_vwap[sym] = event.price
            raw = p.get("raw") or {}
            if raw and self.db:
                from ..data.depth_store import record_depth, spread_from_tick

                spread = record_depth(self.db, sym, raw)
                self.ctx.spread_bps[sym] = spread
            elif raw:
                from ..data.depth_store import spread_from_tick

                _, _, spread = spread_from_tick(raw)
                self.ctx.spread_bps[sym] = spread

        if self.db is not None:
            from ..ops.agent_state import persist_context

            persist_context(self.db, self.ctx)

    def subscribe(self, bus) -> None:
        types = (
            EventType.FII_DII_UPDATE,
            EventType.GIFT_TICK,
            EventType.GIFT_SESSION_CHANGE,
            EventType.IV_UPDATE,
            EventType.PREOPEN_PRICE,
            EventType.TICK,
            EventType.LLM_BIAS_UPDATE,
            EventType.FUTURES_OI_UPDATE,
        )
        for t in types:
            bus.subscribe(t, self.on_event)


def make_context_handler(ctx: MarketContext) -> Callable:
    updater = ContextUpdater(ctx)
    return updater.on_event

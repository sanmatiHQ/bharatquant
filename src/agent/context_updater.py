"""Centralize ingest events → unified MarketContext state vector."""
from __future__ import annotations

import logging
import os
import time
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
        if event.type in (EventType.SESSION_PRE_OPEN, EventType.SESSION_OPEN, EventType.SESSION_CLOSE):
            self.ctx.nse_status = str(p.get("nse_status", self.ctx.nse_status))
            from ..market.market_awareness import refresh_market_awareness

            refresh_market_awareness(self.ctx, self.db)
            logger.info(
                "context_session",
                extra={
                    "nse_status": self.ctx.nse_status,
                    "phase": self.ctx.session_phase,
                    "market_open": self.ctx.market_open,
                },
            )
        elif event.type == EventType.FII_DII_UPDATE:
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
            from ..market.market_awareness import refresh_market_awareness

            refresh_market_awareness(self.ctx, self.db)
            logger.info("context_llm_bias", extra={"bias": self.ctx.llm_bias, "fg": self.ctx.fear_greed_index})
        elif event.type == EventType.FUTURES_OI_UPDATE:
            self.ctx.futures_oi_chg = float(p.get("oi_change_pct", 0) or 0)
        elif event.type == EventType.IV_UPDATE:
            self.ctx.india_vix = float(p.get("vix", p.get("india_vix", 0)))
            from ..market.market_awareness import refresh_market_awareness

            refresh_market_awareness(self.ctx, self.db)
        elif event.type == EventType.PREOPEN_PRICE and event.symbol:
            sym = event.symbol.replace("NSE:", "")
            iep = float(p.get("iep", event.price) or event.price)
            self.ctx.orb_high[sym] = iep
            self.ctx.orb_low[sym] = float(p.get("low", event.price) or event.price)
            if iep > 0:
                self.ctx.session_open[sym] = iep
        elif event.type in (
            EventType.INSIDER_FILING,
            EventType.BLOCK_DEAL,
            EventType.NEWS_ALERT,
            EventType.SHAREHOLDING_UPDATE,
            EventType.MF_HOLDING_UPDATE,
            EventType.CORPORATE_ACTION,
            EventType.BOARD_MEETING,
            EventType.EVENT_CALENDAR,
            EventType.BSE_ANNOUNCEMENT,
        ):
            self._track_corporate(event)
        elif event.type == EventType.PARTICIPANT_OI_UPDATE:
            self.ctx.participant_client_net = float(p.get("client_net", 0) or 0)
            self.ctx.participant_fii_net = float(p.get("fii_net", 0) or 0)
            self.ctx.participant_dii_net = float(p.get("dii_net", 0) or 0)
            self.ctx.retail_fii_divergence = self.ctx.participant_client_net - self.ctx.participant_fii_net
            logger.info(
                "context_participant_oi",
                extra={
                    "client": self.ctx.participant_client_net,
                    "fii": self.ctx.participant_fii_net,
                    "divergence": self.ctx.retail_fii_divergence,
                },
            )
        elif event.type == EventType.TICK and event.symbol:
            sym = event.symbol.replace("NSE:", "")
            if sym not in self.ctx.session_open and event.price > 0:
                ref = self.ctx.orb_low.get(sym) or self.ctx.orb_high.get(sym)
                self.ctx.session_open[sym] = float(ref) if ref else event.price
            if sym not in self.ctx.session_vwap and event.price > 0:
                self.ctx.session_vwap[sym] = event.price
            raw = p.get("raw") or {}
            if raw and self.db:
                from ..data.depth_store import record_depth, orderbook_imbalance_from_tick, spread_from_tick

                spread, obi = record_depth(self.db, sym, raw)
                self.ctx.spread_bps[sym] = spread
                self.ctx.orderbook_imbalance[sym] = obi
                from ..feeds.bar_aggregator import shared_tick_ring

                ring = shared_tick_ring()
                ring.push(sym, event.price)
                self.ctx.tick_atr_bps[sym] = ring.atr_bps(sym)
            elif raw:
                from ..data.depth_store import orderbook_imbalance_from_tick, spread_from_tick

                _, _, spread = spread_from_tick(raw)
                self.ctx.spread_bps[sym] = spread
                self.ctx.orderbook_imbalance[sym] = orderbook_imbalance_from_tick(raw)
                from ..feeds.bar_aggregator import shared_tick_ring

                ring = shared_tick_ring()
                ring.push(sym, event.price)
                self.ctx.tick_atr_bps[sym] = ring.atr_bps(sym)

        if self.db is not None:
            from ..ops.agent_state import persist_context

            persist_context(self.db, self.ctx)

    def _track_corporate(self, event: MarketEvent) -> None:
        from ..intelligence.corporate_activity import (
            normalize_bulk,
            normalize_corp_announce,
            normalize_insider,
            normalize_shareholding,
        )

        p = dict(event.payload or {})
        if event.type == EventType.INSIDER_FILING:
            item = normalize_insider(p)
        elif event.type == EventType.BLOCK_DEAL:
            item = normalize_bulk(p)
        elif event.type == EventType.SHAREHOLDING_UPDATE:
            item = normalize_shareholding(p)
            sym = str(item.get("symbol", ""))
            if sym:
                self.ctx.institutional_holdings = (
                    [item] + [h for h in self.ctx.institutional_holdings if h.get("symbol") != sym]
                )[:12]
        elif event.type == EventType.MF_HOLDING_UPDATE:
            item = normalize_bulk(p)
            item["kind"] = "mf_flow"
            item["category"] = "mf_holding"
        else:
            item = normalize_corp_announce(p)
        if event.type == EventType.CORPORATE_ACTION:
            item = {**item, "kind": "corp_action", "category": str(p.get("subject", p.get("purpose", "action")))[:40]}
            self.ctx.upcoming_events = ([item] + list(self.ctx.upcoming_events))[:15]
        elif event.type == EventType.BOARD_MEETING:
            item = {**item, "kind": "board_meeting", "category": "board_meeting"}
            self.ctx.upcoming_events = ([item] + list(self.ctx.upcoming_events))[:15]
        elif event.type == EventType.EVENT_CALENDAR:
            item = {**item, "kind": "event_calendar", "category": str(p.get("purpose", "calendar"))[:40]}
            self.ctx.upcoming_events = ([item] + list(self.ctx.upcoming_events))[:15]
        elif event.type == EventType.BSE_ANNOUNCEMENT:
            item = {**item, "kind": "bse_announce", "category": "bse", "source": "bse"}
        if event.symbol and not item.get("symbol"):
            item["symbol"] = event.symbol.replace("NSE:", "")
        item["ts"] = int(p.get("_ts", 0)) or int(time.time())
        self.ctx.recent_corporate = [item] + list(self.ctx.recent_corporate)[:19]
        sym = str(item.get("symbol", ""))
        if item.get("category") == "dividend" and sym:
            self.ctx.dividend_watch = ([sym] + [s for s in self.ctx.dividend_watch if s != sym])[:10]
        if item.get("category") == "promoter" and sym:
            self.ctx.promoter_watch = ([sym] + [s for s in self.ctx.promoter_watch if s != sym])[:10]
        logger.info(
            "context_corporate",
            extra={"kind": item.get("kind"), "symbol": sym, "category": item.get("category")},
        )

    def subscribe(self, bus) -> None:
        types = (
            EventType.SESSION_PRE_OPEN,
            EventType.SESSION_OPEN,
            EventType.SESSION_CLOSE,
            EventType.FII_DII_UPDATE,
            EventType.GIFT_TICK,
            EventType.GIFT_SESSION_CHANGE,
            EventType.IV_UPDATE,
            EventType.PREOPEN_PRICE,
            EventType.TICK,
            EventType.LLM_BIAS_UPDATE,
            EventType.FUTURES_OI_UPDATE,
            EventType.INSIDER_FILING,
            EventType.BLOCK_DEAL,
            EventType.NEWS_ALERT,
            EventType.SHAREHOLDING_UPDATE,
            EventType.MF_HOLDING_UPDATE,
            EventType.CORPORATE_ACTION,
            EventType.BOARD_MEETING,
            EventType.EVENT_CALENDAR,
            EventType.PARTICIPANT_OI_UPDATE,
            EventType.BSE_ANNOUNCEMENT,
            EventType.RECONCILE_ALERT,
        )
        for t in types:
            bus.subscribe(t, self.on_event)


def make_context_handler(ctx: MarketContext) -> Callable:
    updater = ContextUpdater(ctx)
    return updater.on_event

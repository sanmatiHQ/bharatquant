"""Literature-backed strategies — QuantifiedStrategies, TradingView PROTOS, Kakushadze 151."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy

_IST = ZoneInfo("Asia/Kolkata")


def _sym(event: MarketEvent) -> str:
    return (event.symbol or "").replace("NSE:", "")


class ConnorsIBSStrategy:
    """Connors Internal Bar Strength mean reversion — QuantifiedStrategies / PROTOS."""

    id = "connors_ibs"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        ibs = float((event.payload or {}).get("ibs", 0.5))
        rsi = float((event.payload or {}).get("rsi", 50))
        if ibs <= 0.2 and rsi < 40 and ctx.regime in ("NEUTRAL", "BULL", "RISK_ON"):
            return Signal(self.id, sym, "BUY", "MIS", 0.7, f"ibs_os_{ibs:.2f}")
        if ibs >= 0.8 and rsi > 65:
            return Signal(self.id, sym, "SELL", "MIS", 0.66, f"ibs_ob_{ibs:.2f}")
        return None


class CrabelNR7Strategy:
    """Crabel NR7 narrow-range breakout — PROTOS / 151 Trading Strategies ch.3."""

    id = "crabel_nr7"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        if not int(p.get("nr7", 0)):
            return None
        r3m = float(p.get("r3m", 0))
        vol_ratio = float(p.get("vol_ratio", 1.0))
        if r3m > 0.003 and vol_ratio >= 1.2:
            conf = min(0.78, 0.62 + r3m * 12 + (vol_ratio - 1) * 0.08)
            return Signal(self.id, sym, "BUY", "MIS", conf, "nr7_break_up")
        if r3m < -0.003 and vol_ratio >= 1.2:
            return Signal(self.id, sym, "SELL", "MIS", 0.64, "nr7_break_dn")
        return None


class ZScoreReversionStrategy:
    """Z-score stretch fade — Kakushadze stat-arb + TradingView Reversal Pro."""

    id = "zscore_reversion"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        z = float((event.payload or {}).get("z_score", 0))
        vol_ratio = float((event.payload or {}).get("vol_ratio", 1.0))
        if z <= -2.0 and vol_ratio < 2.5 and ctx.india_vix < 24:
            conf = min(0.8, 0.65 + abs(z) * 0.05)
            return Signal(self.id, sym, "BUY", "CNC", conf, f"z_rev_long_{z:.1f}")
        if z >= 2.0 and vol_ratio < 2.5:
            return Signal(self.id, sym, "SELL", "MIS", 0.67, f"z_rev_short_{z:.1f}")
        return None


class MomentumConsensusStrategy:
    """Multi-factor consensus — TradingView Momentum Consensus Heatmap / Quant Confluence."""

    id = "momentum_consensus"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        votes = 0
        r3m = float(p.get("r3m", 0))
        rsi = float(p.get("rsi", 50))
        vol_ratio = float(p.get("vol_ratio", 1.0))
        ema_up = int(p.get("ema_cross_up", 0))
        if r3m > 0.004:
            votes += 1
        if 48 < rsi < 68:
            votes += 1
        if vol_ratio >= 1.3:
            votes += 1
        if ema_up:
            votes += 1
        if ctx.fii_net_cr > 0:
            votes += 1
        if votes >= 4 and ctx.regime in ("BULL", "RISK_ON", "NEUTRAL"):
            conf = min(0.85, 0.6 + votes * 0.05)
            ctx.strategy_scores[f"consensus_{sym}"] = float(votes)
            return Signal(self.id, sym, "BUY", "CNC", conf, f"consensus_{votes}/5")
        votes_short = 0
        if r3m < -0.004:
            votes_short += 1
        if rsi > 72:
            votes_short += 1
        if not ema_up:
            votes_short += 1
        if ctx.fii_net_cr < -200:
            votes_short += 1
        if votes_short >= 3 and ctx.regime in ("BEAR", "RISK_OFF"):
            return Signal(self.id, sym, "SELL", "MIS", 0.66, f"consensus_short_{votes_short}")
        return None


class EmaCrossRsiStrategy:
    """EMA 9/21 + RSI filter — Smart Trend Dashboard (TradingView)."""

    id = "ema_cross_rsi"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        if not int(p.get("ema_cross_up", 0)):
            return None
        rsi = float(p.get("rsi", 50))
        r1m = float(p.get("r1m", 0))
        if 42 < rsi < 68 and r1m > 0:
            return Signal(self.id, sym, "BUY", "MIS", 0.71, "ema_rsi_long")
        if rsi > 72 and r1m < 0:
            return Signal(self.id, sym, "SELL", "MIS", 0.64, "ema_rsi_fade")
        return None


class LiquiditySweepStrategy:
    """Liquidity sweep reclaim — TradingView SMC / Liquidity Sweep & Golden Zone."""

    id = "liquidity_sweep"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        low = float(p.get("low", event.price))
        high = float(p.get("high", event.price))
        close = float(p.get("close", event.price))
        low_20 = float(p.get("low_20", 0))
        if low_20 <= 0 or high <= low:
            return None
        mid = (high + low) / 2.0
        swept = low < low_20 * 0.998 and close > mid
        if swept and close > low_20:
            vol_ratio = float(p.get("vol_ratio", 1.0))
            conf = min(0.82, 0.68 + (vol_ratio - 1) * 0.06)
            return Signal(self.id, sym, "BUY", "MIS", conf, "liq_sweep_reclaim")
        high_20 = float(p.get("high_20", 0))
        if high_20 > 0 and high > high_20 * 1.002 and close < mid and close < high_20:
            return Signal(self.id, sym, "SELL", "MIS", 0.65, "liq_sweep_high")
        return None


class TurnaroundTuesdayStrategy:
    """Turnaround Tuesday calendar effect — QuantifiedStrategies mean reversion."""

    id = "turnaround_tuesday"
    listens_to = {EventType.SESSION_OPEN}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        now = datetime.now(_IST)
        if now.weekday() != 1:
            return None
        if ctx.gift_nifty_change_pct < -0.15 or ctx.fii_net_cr < -150:
            if ctx.regime not in ("RISK_OFF", "BEAR"):
                return Signal(self.id, "NIFTYBEES", "BUY", "CNC", 0.69, "tuesday_bounce")
        return None

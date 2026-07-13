"""US-origin strategies localized for NSE/BSE — paper-learn what works in India."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy
from .market_session import ist_now, is_monthly_expiry_day, session_phase


def _sym(event: MarketEvent) -> str:
    return (event.symbol or "").replace("NSE:", "")


class IndiaPowerHourStrategy:
    """US power hour (last 60m) → IST 14:30–15:30 momentum continuation."""

    id = "india_power_hour"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if session_phase() != "power_hour":
            return None
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        r3m = float(p.get("r3m", 0))
        vol_ratio = float(p.get("vol_ratio", 1.0))
        if r3m > 0.0035 and vol_ratio >= 1.15 and ctx.regime in ("BULL", "RISK_ON", "NEUTRAL"):
            conf = min(0.8, 0.62 + r3m * 10)
            return Signal(self.id, sym, "BUY", "MIS", conf, "in_power_hour_mom")
        if r3m < -0.0035 and vol_ratio >= 1.1:
            return Signal(self.id, sym, "SELL", "MIS", 0.64, "in_power_hour_fade")
        return None


class IndiaLunchFadeStrategy:
    """US lunch doldrums fade → IST 12:00–13:30 low-liquidity mean reversion."""

    id = "india_lunch_fade"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if session_phase() != "lunch":
            return None
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        ibs = float(p.get("ibs", 0.5))
        z = float(p.get("z_score", 0))
        if ibs <= 0.18 and z <= -1.2 and ctx.india_vix < 26:
            return Signal(self.id, sym, "BUY", "MIS", 0.68, "lunch_ibs_os")
        if ibs >= 0.82 and z >= 1.2:
            return Signal(self.id, sym, "SELL", "MIS", 0.63, "lunch_ibs_ob")
        return None


class IndiaOpeningDriveStrategy:
    """US opening-drive / first-hour thrust → IST 09:15–09:45 breakout."""

    id = "india_opening_drive"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if session_phase() != "opening_drive":
            return None
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        r1m = float(p.get("r1m", 0))
        r3m = float(p.get("r3m", 0))
        vol_ratio = float(p.get("vol_ratio", 1.0))
        if r1m > 0.002 and r3m > 0.004 and vol_ratio >= 1.25:
            return Signal(self.id, sym, "BUY", "MIS", 0.72, "opening_drive_up")
        if r1m < -0.002 and r3m < -0.004 and vol_ratio >= 1.2:
            return Signal(self.id, sym, "SELL", "MIS", 0.65, "opening_drive_dn")
        return None


class NiftyBuyTheDipStrategy:
    """QS SPY buy-the-dip → NIFTYBEES after multi-day drawdown."""

    id = "nifty_buy_the_dip"
    listens_to = {EventType.BAR_CLOSE_1D, EventType.SESSION_OPEN}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        p = event.payload or {}
        if event.type == EventType.BAR_CLOSE_1D:
            if sym != "NIFTYBEES":
                return None
            ret_5d = float(p.get("ret_5d", 0))
            ctx.strategy_scores["nifty_ret_5d"] = ret_5d
            if ret_5d < -0.015 and ctx.regime not in ("RISK_OFF",):
                conf = min(0.78, 0.62 + abs(ret_5d) * 8)
                return Signal(self.id, "NIFTYBEES", "BUY", "CNC", conf, f"buy_dip_{ret_5d:.3f}")
            return None
        if event.type == EventType.SESSION_OPEN:
            ret_5d = float(ctx.strategy_scores.get("nifty_ret_5d", 0))
            if ret_5d < -0.015 and ctx.regime not in ("RISK_OFF",):
                conf = min(0.78, 0.62 + abs(ret_5d) * 8)
                return Signal(self.id, "NIFTYBEES", "BUY", "CNC", conf, f"buy_dip_open_{ret_5d:.3f}")
        return None


class IndiaDualRotationStrategy:
    """Antonacci SPY/TLT dual momentum → NIFTYBEES vs GOLDBEES relative strength."""

    id = "india_dual_rotation"
    listens_to = {EventType.BAR_CLOSE_1D, EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if sym not in ("NIFTYBEES", "GOLDBEES"):
            return None
        p = event.payload or {}
        mom = float(p.get("ret_5d", p.get("r3m", 0)))
        ctx.strategy_scores[f"rot_{sym}"] = mom
        nifty = ctx.strategy_scores.get("rot_NIFTYBEES")
        gold = ctx.strategy_scores.get("rot_GOLDBEES")
        if nifty is None or gold is None:
            return None
        if nifty > 0.012 and nifty > gold + 0.005:
            return Signal(self.id, "NIFTYBEES", "BUY", "CNC", 0.7, "dual_rot_equity")
        if gold > 0.008 and gold > nifty + 0.003:
            return Signal(self.id, "GOLDBEES", "BUY", "CNC", 0.68, "dual_rot_gold")
        return None


class AthBreakoutIndiaStrategy:
    """QS all-time-high proximity breakout — Donchian high_20 on NSE liquid names."""

    id = "ath_breakout_in"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        if not int(p.get("near_high_20", 0)):
            return None
        r3m = float(p.get("r3m", 0))
        vol_ratio = float(p.get("vol_ratio", 1.0))
        if r3m > 0.002 and vol_ratio >= 1.3 and ctx.regime in ("BULL", "RISK_ON", "NEUTRAL"):
            conf = min(0.82, 0.66 + vol_ratio * 0.05)
            return Signal(self.id, sym, "BUY", "CNC", conf, "ath_prox_break")
        return None


class LowerHighsFadeStrategy:
    """QS lower-highs distribution — fade weak rallies after LH streak."""

    id = "lower_highs_fade"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        streak = int(p.get("lower_high_streak", 0))
        rsi = float(p.get("rsi", 50))
        if streak >= 2 and rsi < 55:
            conf = min(0.75, 0.6 + streak * 0.05)
            return Signal(self.id, sym, "SELL", "MIS", conf, f"lh_streak_{streak}")
        return None


class UsOvernightFollowStrategy:
    """US close → GIFT → NSE open follow-through (localized overnight drift)."""

    id = "us_overnight_follow"
    listens_to = {EventType.SESSION_OPEN, EventType.GIFT_TICK}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if event.type == EventType.GIFT_TICK:
            ctx.gift_nifty_change_pct = float((event.payload or {}).get("change_pct", 0))
            return None
        gap = ctx.gift_nifty_change_pct
        if gap > 0.25 and ctx.regime in ("RISK_ON", "BULL", "NEUTRAL"):
            conf = min(0.84, 0.65 + gap)
            return Signal(self.id, "NIFTYBEES", "BUY", "MIS", conf, "us_follow_gap_up")
        if gap < -0.35 and ctx.fii_net_cr > 0:
            return Signal(self.id, "NIFTYBEES", "BUY", "MIS", 0.66, "us_follow_gap_fade")
        return None


class ExpiryWeekCautionStrategy:
    """US monthly OPEX caution → India monthly expiry Thursday defensive fade."""

    id = "expiry_week_caution"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if not is_monthly_expiry_day():
            return None
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        rsi = float(p.get("rsi", 50))
        z = float(p.get("z_score", 0))
        if rsi > 72 or z > 1.8:
            return Signal(self.id, sym, "SELL", "MIS", 0.67, "expiry_thu_fade")
        if rsi < 32 and z < -1.5:
            return Signal(self.id, sym, "BUY", "MIS", 0.65, "expiry_thu_bounce")
        return None


class MondayEffectIndiaStrategy:
    """US Monday effect → India Monday open bounce after weak GIFT weekend gap."""

    id = "monday_effect_in"
    listens_to = {EventType.SESSION_OPEN}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if ist_now().weekday() != 0:
            return None
        gap = ctx.gift_nifty_change_pct
        if gap < -0.2 and ctx.regime in ("NEUTRAL", "BULL", "RISK_ON"):
            return Signal(self.id, "NIFTYBEES", "BUY", "CNC", 0.68, "monday_reversal_in")
        return None

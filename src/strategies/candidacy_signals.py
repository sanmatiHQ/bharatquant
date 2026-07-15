"""Tier-2 candidacy-only signals — shadow first, no capital until lifecycle promotion."""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy

_IST = ZoneInfo("Asia/Kolkata")


def _sym(event: MarketEvent) -> str:
    return (event.symbol or "").replace("NSE:", "").upper()


class IndexReconstitutionStrategy:
    id = "index_reconstitution"
    listens_to = {EventType.NEWS_ALERT, EventType.BAR_CLOSE_1D}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if event.type != EventType.NEWS_ALERT:
            return None
        desc = str(event.payload.get("desc") or event.payload.get("subject") or "").lower()
        if not re.search(r"nifty|sensex|next\s*50|index.*(add|delet|inclus|exclus)", desc):
            return None
        sym = _sym(event)
        if not sym:
            return None
        side = "BUY" if "add" in desc or "inclus" in desc else "SELL"
        return Signal(self.id, sym, side, "CNC", 0.62, "index_reconstitution_window")


class AsmGsmEntryStrategy:
    id = "asm_gsm_entry"
    listens_to = {EventType.BAR_CLOSE_5M}

    def __init__(self, db=None) -> None:
        self.db = db

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if not self.db:
            return None
        sym = _sym(event)
        row = self.db._conn.execute(
            "SELECT stage, updated_ts FROM asm_gsm_symbols WHERE symbol=? ORDER BY updated_ts DESC LIMIT 1",
            (sym,),
        ).fetchone()
        if not row:
            return None
        age_h = (time.time() - int(row["updated_ts"])) / 3600.0
        if age_h > 72:
            return None
        stage = str(row["stage"]).upper()
        if stage not in ("ASM", "GSM", "STAGE1", "STAGE2"):
            return None
        return Signal(self.id, sym, "SELL", "CNC", 0.58, f"asm_gsm_entry_{stage}")


class FoBanUnwindStrategy:
    id = "fo_ban_unwind"
    listens_to = {EventType.NEWS_ALERT, EventType.FUTURES_OI_UPDATE}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        text = str(event.payload.get("desc") or event.payload.get("ban") or "").lower()
        sym = _sym(event)
        if "ban" not in text and event.type != EventType.FUTURES_OI_UPDATE:
            return None
        if event.type == EventType.FUTURES_OI_UPDATE and not event.payload.get("mwpl_ban"):
            return None
        if not sym:
            return None
        return Signal(self.id, sym, "SELL", "CNC", 0.65, "fo_ban_forced_unwind")


class PromoterPledgeSignalStrategy:
    id = "promoter_pledge_signal"
    listens_to = {EventType.SHAREHOLDING_UPDATE}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        deltas = event.payload.get("deltas") or {}
        pledge_d = float(deltas.get("promoter_pledge_pct") or deltas.get("pledge_pct") or 0)
        if pledge_d <= 0.5:
            return None
        sym = _sym(event)
        if not sym:
            return None
        return Signal(self.id, sym, "SELL", "CNC", min(0.85, 0.55 + pledge_d * 0.05), "promoter_pledge_increase")


class SipFlowSeasonalityStrategy:
    id = "sip_flow_seasonality"
    listens_to = {EventType.BAR_CLOSE_1D, EventType.SESSION_OPEN}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        day = datetime.now(_IST).day
        if day < 5 or day > 18:
            return None
        return Signal(self.id, "NIFTYBEES", "BUY", "CNC", 0.55, f"sip_flow_day_{day}")


class GiftBasisConvergenceStrategy:
    id = "gift_basis_convergence"
    listens_to = {EventType.GIFT_TICK, EventType.SESSION_OPEN, EventType.PREOPEN_PRICE}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if event.type == EventType.GIFT_TICK:
            ctx.gift_nifty_change_pct = float(event.payload.get("change_pct", 0))
            return None
        gap = ctx.gift_nifty_change_pct
        if abs(gap) < 0.15:
            return None
        side = "SELL" if gap > 0 else "BUY"
        return Signal(self.id, "NIFTYBEES", side, "CNC", 0.6, "gift_basis_convergence_open")


class RetailContrarianFadeStrategy:
    id = "retail_contrarian_fade"
    listens_to = {EventType.PARTICIPANT_OI_UPDATE, EventType.BAR_CLOSE_1D}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        retail_net = float(ctx.participant_client_net or event.payload.get("client_net") or 0)
        if abs(retail_net) < 500.0:
            return None
        sym = _sym(event) or "NIFTYBEES"
        side = "SELL" if retail_net > 1500 else ("BUY" if retail_net < -1500 else "")
        if not side:
            return None
        return Signal(self.id, sym, side, "CNC", 0.57, f"retail_fade_net_{retail_net:.0f}")


class PeadContinuationStrategy:
    id = "pead_continuation"
    listens_to = {EventType.CORPORATE_ACTION, EventType.BAR_CLOSE_1D}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        text = str(event.payload.get("desc") or event.payload.get("purpose") or "").lower()
        if "result" not in text and "earnings" not in text and "quarter" not in text:
            return None
        beat = "beat" in text or "surpass" in text or "growth" in text
        miss = "miss" in text or "decline" in text or "loss" in text
        if not beat and not miss:
            return None
        sym = _sym(event)
        if not sym:
            return None
        return Signal(self.id, sym, "BUY" if beat else "SELL", "CNC", 0.63, "pead_continuation")


class CircuitBandFlowStrategy:
    id = "circuit_band_flow"
    listens_to = {EventType.TICK, EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        px = float(event.price or event.payload.get("close") or 0)
        if px <= 0 or not sym:
            return None
        upper = float(event.payload.get("upper_circuit") or 0)
        lower = float(event.payload.get("lower_circuit") or 0)
        if upper <= 0:
            return None
        dist_upper = (upper - px) / upper
        dist_lower = (px - lower) / px if lower > 0 else 1.0
        if dist_upper < 0.02:
            return Signal(self.id, sym, "BUY", "CNC", 0.6, "approach_upper_circuit")
        if lower > 0 and dist_lower < 0.02:
            return Signal(self.id, sym, "SELL", "CNC", 0.6, "approach_lower_circuit")
        return None


class RegulatoryCatalystStrategy:
    id = "regulatory_catalyst"
    listens_to = {EventType.NEWS_ALERT, EventType.EVENT_CALENDAR}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        text = str(event.payload.get("desc") or event.payload.get("title") or "").lower()
        if not re.search(r"sebi|lot size|margin|circuit|effective from", text):
            return None
        sym = _sym(event) or "NIFTYBEES"
        return Signal(self.id, sym, "BUY", "CNC", 0.56, "regulatory_catalyst_window")


class Proximity52WHighStrategy:
    """George & Hwang (2004) 52-week-high momentum — distinct from generic price momentum:
    proximity to the 52-week high itself (not trailing return) is the documented anomaly."""

    id = "proximity_52w_high"
    listens_to = {EventType.BAR_CLOSE_1D}

    def __init__(self, db=None) -> None:
        self.db = db

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if not self.db:
            return None
        sym = _sym(event)
        if not sym:
            return None
        rows = self.db._conn.execute(
            "SELECT close FROM bar_log WHERE symbol=? AND interval='1d' ORDER BY ts DESC LIMIT 252",
            (sym,),
        ).fetchall()
        if len(rows) < 60:
            return None
        closes = [float(r["close"]) for r in rows]
        last = closes[0]
        hi_52w = max(closes)
        if hi_52w <= 0:
            return None
        ratio = last / hi_52w
        if ratio < 0.95:
            return None
        confidence = min(0.72, 0.5 + (ratio - 0.95) * 4.0)
        return Signal(self.id, sym, "BUY", "CNC", round(confidence, 3), f"proximity_52w_high_{ratio:.3f}")


class LowVolatilityAnomalyStrategy:
    """Ang, Hodrick, Xing & Zhang (2006) low-volatility anomaly — low realized-vol names
    show better risk-adjusted returns than the market rewards them for; avoids dead laggards
    by requiring non-negative trailing momentum alongside the low-vol filter."""

    id = "low_vol_anomaly"
    listens_to = {EventType.BAR_CLOSE_1D}

    def __init__(self, db=None) -> None:
        self.db = db

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if not self.db:
            return None
        sym = _sym(event)
        if not sym:
            return None
        rows = self.db._conn.execute(
            "SELECT close FROM bar_log WHERE symbol=? AND interval='1d' ORDER BY ts DESC LIMIT 21",
            (sym,),
        ).fetchall()
        if len(rows) < 21:
            return None
        closes = [float(r["close"]) for r in reversed(rows)]
        rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]
        if len(rets) < 15:
            return None
        mean_r = sum(rets) / len(rets)
        var = sum((r - mean_r) ** 2 for r in rets) / len(rets)
        ann_vol = (var ** 0.5) * (252 ** 0.5)
        mom_20d = (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0.0
        if ann_vol >= 0.20 or mom_20d < 0:
            return None
        confidence = min(0.68, 0.55 + (0.20 - ann_vol))
        return Signal(self.id, sym, "BUY", "CNC", round(confidence, 3), f"low_vol_anomaly_{ann_vol:.3f}")


class DeliveryConvictionStrategy:
    """India-specific: NSE delivery % distinguishes genuine accumulation from intraday churn.
    High delivery % on an up day signals real (not speculative/leveraged) buying interest —
    the same underlying data institutional NSE desks watch, rarely modeled at retail scale."""

    id = "delivery_conviction"
    listens_to = {EventType.VOLUME_ANOMALY}

    def __init__(self, db=None) -> None:
        self.db = db

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if not self.db:
            return None
        sym = _sym(event)
        if not sym:
            return None
        dp = event.payload.get("delivery_pct")
        if dp is None:
            return None
        dp = float(dp)
        if dp < 65.0:
            return None
        rows = self.db._conn.execute(
            "SELECT close FROM bar_log WHERE symbol=? AND interval='1d' ORDER BY ts DESC LIMIT 2",
            (sym,),
        ).fetchall()
        if len(rows) < 2:
            return None
        last, prev = float(rows[0]["close"]), float(rows[1]["close"])
        if prev <= 0 or last <= prev:
            return None
        chg = (last - prev) / prev
        confidence = min(0.7, 0.55 + (dp - 65.0) / 100.0 + min(0.05, chg))
        return Signal(self.id, sym, "BUY", "CNC", round(confidence, 3), f"delivery_conviction_{dp:.0f}pct")

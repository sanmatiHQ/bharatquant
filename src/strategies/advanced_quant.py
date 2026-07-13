"""Advanced quant strategies — macro, microstructure, composite alpha, self-learning lab."""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy

_ENERGY_SYMS = frozenset({"ONGC", "RELIANCE", "BPCL", "IOC", "GAIL", "HINDPETRO", "OIL"})


def _sym(event: MarketEvent) -> str:
    return (event.symbol or "").replace("NSE:", "")


def _score_ctx(ctx: MarketContext) -> float:
    """Multi-factor confluence score 0–1."""
    s = 0.0
    if ctx.gift_nifty_change_pct > 0.15:
        s += 0.15
    elif ctx.gift_nifty_change_pct < -0.15:
        s -= 0.15
    if ctx.fii_net_cr > 300:
        s += 0.2
    elif ctx.fii_net_cr < -300:
        s -= 0.2
    if ctx.us_sp_change_pct > 0.3:
        s += 0.1
    if ctx.crude_change_pct > 1.5:
        s -= 0.1
    if ctx.usd_inr_change_pct > 0.2:
        s -= 0.05
    if ctx.india_vix > 22:
        s -= 0.1
    elif ctx.india_vix < 14:
        s += 0.05
    return max(-1.0, min(1.0, s))


class MacroConfluenceStrategy:
    """Cross-asset macro alignment — GIFT + FII + US futures + VIX."""

    id = "macro_confluence"
    listens_to = {EventType.GIFT_SESSION_CHANGE, EventType.FII_DII_UPDATE, EventType.SESSION_OPEN}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        score = _score_ctx(ctx)
        ctx.strategy_scores[self.id] = score
        if score >= 0.35 and ctx.gift_nifty_change_pct > 0.1 and ctx.fii_net_cr > 200:
            return Signal(self.id, "NIFTYBEES", "BUY", "CNC", 0.72, f"macro_bull_{score:.2f}")
        if score <= -0.35:
            return Signal(self.id, "NIFTYBEES", "SELL", "CNC", 0.68, f"macro_bear_{score:.2f}")
        return None


class GiftFiiSyncStrategy:
    """GIFT Nifty lead + FII flow confirmation for index proxy."""

    id = "gift_fii_sync"
    listens_to = {EventType.GIFT_TICK, EventType.FII_DII_UPDATE}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        gift = ctx.gift_nifty_change_pct
        fii = ctx.fii_net_cr
        if gift > 0.25 and fii > 0:
            return Signal(self.id, "NIFTYBEES", "BUY", "CNC", 0.7, "gift_fii_long")
        if gift < -0.25 and fii < -200:
            return Signal(self.id, "NIFTYBEES", "SELL", "CNC", 0.68, "gift_fii_short")
        return None


class VolumeBreakoutStrategy:
    """Volume spike + range breakout — institutional accumulation detector."""

    id = "volume_breakout"
    listens_to = {EventType.BAR_CLOSE_5M, EventType.VOLUME_ANOMALY}

    def __init__(self) -> None:
        self._high: Dict[str, float] = {}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        vol_ratio = float(p.get("vol_ratio", 1.0))
        high = float(p.get("high", event.price))
        close = float(p.get("close", event.price))
        self._high[sym] = max(self._high.get(sym, high), high)
        prev_high = self._high.get(sym, high)
        if vol_ratio >= 2.0 and close > prev_high * 0.998 and close >= high * 0.995:
            r3m = float(p.get("r3m", 0))
            conf = min(0.85, 0.62 + vol_ratio * 0.05 + max(0, r3m) * 10)
            return Signal(self.id, sym, "BUY", "MIS", conf, f"vol_brk_{vol_ratio:.1f}x")
        return None


class BollingerSqueezeStrategy:
    """Volatility compression → expansion breakout (TTM Squeeze style)."""

    id = "bollinger_squeeze"
    listens_to = {EventType.BAR_CLOSE_5M}

    def __init__(self) -> None:
        self._bb_hist: Dict[str, Deque[float]] = {}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        bb_w = float(p.get("bb_width", 1.0))
        hist = self._bb_hist.setdefault(sym, deque(maxlen=10))
        hist.append(bb_w)
        if len(hist) < 5:
            return None
        avg_w = sum(hist) / len(hist)
        r3m = float(p.get("r3m", 0))
        if avg_w < 1.2 and bb_w > avg_w * 1.4 and r3m > 0.003:
            return Signal(self.id, sym, "BUY", "MIS", 0.71, "bb_squeeze_up")
        if avg_w < 1.2 and bb_w > avg_w * 1.4 and r3m < -0.003:
            return Signal(self.id, sym, "SELL", "MIS", 0.69, "bb_squeeze_dn")
        return None


class DualMomentumProStrategy:
    """Absolute + relative dual momentum with acceleration filter."""

    id = "dual_momentum_pro"
    listens_to = {EventType.BAR_CLOSE_5M, EventType.BAR_CLOSE_15M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym or event.type != EventType.BAR_CLOSE_5M:
            return None
        p = event.payload or {}
        r1m = float(p.get("r1m", 0))
        r3m = float(p.get("r3m", 0))
        rsi = float(p.get("rsi", 50))
        if r1m > 0 and r3m > 0.005 and r1m > r3m / 3 and 45 < rsi < 72:
            conf = min(0.82, 0.65 + r3m * 15)
            return Signal(self.id, sym, "BUY", "CNC", conf, "dual_mom_long")
        if r1m < 0 and r3m < -0.005 and rsi > 75:
            return Signal(self.id, sym, "SELL", "MIS", 0.67, "dual_mom_fade")
        return None


class FiiDivergenceStrategy:
    """FII inflow regime but stock lagging — mean-reversion catch-up."""

    id = "fii_divergence"
    listens_to = {EventType.BAR_CLOSE_5M, EventType.FII_DII_UPDATE}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        if ctx.fii_net_cr < 400:
            return None
        sym = _sym(event)
        if not sym or event.type != EventType.BAR_CLOSE_5M:
            return None
        p = event.payload or {}
        r3m = float(p.get("r3m", 0))
        rsi = float(p.get("rsi", 50))
        if r3m < -0.004 and rsi < 42 and ctx.regime in ("RISK_ON", "NEUTRAL", "BULL"):
            return Signal(self.id, sym, "BUY", "CNC", 0.7, "fii_catchup")
        return None


class VwapVolumeConfirmStrategy:
    """VWAP reclaim with volume confirmation — order-flow proxy."""

    id = "vwap_volume_confirm"
    listens_to = {EventType.VWAP_CROSS, EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        if event.type == EventType.VWAP_CROSS:
            side = (event.payload or {}).get("side")
            if side == "above":
                ctx.strategy_scores[f"{sym}_vwap"] = 1.0
            return None
        p = event.payload or {}
        vol_ratio = float(p.get("vol_ratio", 1.0))
        if ctx.strategy_scores.get(f"{sym}_vwap") == 1.0 and vol_ratio >= 1.5:
            ctx.strategy_scores.pop(f"{sym}_vwap", None)
            return Signal(self.id, sym, "BUY", "MIS", 0.73, "vwap_vol_confirm")
        return None


class CrudeEnergyBetaStrategy:
    """Crude spike → energy beta long; crude crash → fade energy."""

    id = "crude_energy_beta"
    listens_to = {EventType.GIFT_SESSION_CHANGE, EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if event.type == EventType.GIFT_SESSION_CHANGE:
            return None
        if sym not in _ENERGY_SYMS:
            return None
        crude = ctx.crude_change_pct
        p = event.payload or {}
        r3m = float(p.get("r3m", 0))
        if crude > 2.0 and r3m > 0:
            return Signal(self.id, sym, "BUY", "CNC", 0.69, "crude_beta_long")
        if crude < -2.0 and r3m < 0:
            return Signal(self.id, sym, "SELL", "MIS", 0.66, "crude_beta_fade")
        return None


class RsiRegimeAdaptiveStrategy:
    """RSI thresholds adapt to macro regime — not fixed 30/70."""

    id = "rsi_regime_adaptive"
    listens_to = {EventType.BAR_CLOSE_5M}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym:
            return None
        rsi = float((event.payload or {}).get("rsi", 50))
        if ctx.regime in ("RISK_ON", "BULL", "NEUTRAL") and rsi < 38:
            return Signal(self.id, sym, "BUY", "MIS", 0.68, "rsi_regime_os")
        if ctx.regime in ("RISK_OFF", "BEAR", "HIGH_VOL") and rsi > 68:
            return Signal(self.id, sym, "SELL", "MIS", 0.67, "rsi_regime_ob")
        return None


class AdaptiveAlphaStrategy:
    """Composite scorer — fuses momentum, macro, volume, RSI into one alpha signal."""

    id = "adaptive_alpha"
    listens_to = {EventType.BAR_CLOSE_5M, EventType.GIFT_SESSION_CHANGE, EventType.FII_DII_UPDATE}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = _sym(event)
        if not sym or event.type != EventType.BAR_CLOSE_5M:
            return None
        p = event.payload or {}
        macro = _score_ctx(ctx)
        r3m = float(p.get("r3m", 0))
        vol_ratio = float(p.get("vol_ratio", 1.0))
        rsi = float(p.get("rsi", 50))
        alpha = macro * 0.35 + r3m * 25 + (vol_ratio - 1) * 0.1
        if rsi < 35:
            alpha += 0.1
        if rsi > 70:
            alpha -= 0.1
        ctx.strategy_scores[f"alpha_{sym}"] = alpha
        if alpha >= 0.45:
            conf = min(0.88, 0.6 + alpha * 0.4)
            return Signal(self.id, sym, "BUY", "CNC", conf, f"alpha_{alpha:.2f}")
        if alpha <= -0.4:
            return Signal(self.id, sym, "SELL", "MIS", 0.65, f"alpha_short_{alpha:.2f}")
        return None


class StrategyLabStrategy:
    """Self-learning meta-strategy — promotes patterns that won recently in ledger."""

    id = "strategy_lab"
    listens_to = {EventType.SESSION_OPEN, EventType.BAR_CLOSE_5M}

    def __init__(self, db=None) -> None:
        self.db = db
        self._winning: Dict[str, float] = {}
        self._last_refresh = 0.0

    def _refresh_winners(self) -> None:
        if self.db is None or time.time() - self._last_refresh < 300:
            return
        self._last_refresh = time.time()
        try:
            rows = self.db.conn.execute(
                """
                SELECT strategy_id, realized_pnl AS pnl
                FROM strategy_pnl
                WHERE realized_pnl > 0
                ORDER BY realized_pnl DESC
                LIMIT 5
                """
            ).fetchall()
            self._winning = {r["strategy_id"]: float(r["pnl"]) for r in rows}
        except Exception:
            self._winning = {}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        self._refresh_winners()
        if event.type == EventType.SESSION_OPEN:
            return None
        sym = _sym(event)
        if not sym:
            return None
        p = event.payload or {}
        r3m = float(p.get("r3m", 0))
        vol_ratio = float(p.get("vol_ratio", 1.0))
        if not self._winning:
            if r3m > 0.006 and vol_ratio > 1.8 and ctx.fii_net_cr > 0:
                return Signal(self.id, sym, "BUY", "MIS", 0.66, "lab_explore_long")
            return None
        best = max(self._winning.values())
        if r3m > 0.004 and vol_ratio > 1.3 and ctx.regime != "RISK_OFF":
            conf = min(0.8, 0.62 + best / 5000)
            top = next(iter(self._winning))
            return Signal(self.id, sym, "BUY", "CNC", conf, f"lab_promote_{top}")
        return None

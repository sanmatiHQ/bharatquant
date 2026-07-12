"""Load and run registered strategies."""
from __future__ import annotations

from typing import List, Optional, Type

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy
from .bulk_accumulation import BulkAccumulationStrategy
from .cash_futures_basis import CashFuturesBasisStrategy
from .combined_momentum import CombinedMomentumStrategy
from .earnings_vol import EarningsVolStrategy
from .expiry_gamma import ExpiryGammaStrategy
from .fii_regime import FiiRegimeStrategy
from .gift_gap import GiftGapStrategy
from .global_risk_beta import GlobalRiskBetaStrategy
from .insider_cluster import InsiderClusterStrategy
from .iv_premium_sell import IvPremiumSellStrategy
from .opening_range import OpeningRangeStrategy
from .pairs_stat_arb import PairsStatArbStrategy
from .quality_momentum import QualityMomentumStrategy
from .short_term_reversal import ShortTermReversalStrategy
from .stop_loss_guard import StopLossGuardStrategy
from .turtle_breakout import TurtleBreakoutStrategy
from .vwap_reversion import VwapReversionStrategy


_BUILTIN: dict[str, Type[Strategy]] = {
    "combined_momentum": CombinedMomentumStrategy,
    "fii_regime": FiiRegimeStrategy,
    "gift_gap": GiftGapStrategy,
    "opening_range": OpeningRangeStrategy,
    "short_term_reversal": ShortTermReversalStrategy,
    "stop_loss_guard": StopLossGuardStrategy,
    "turtle_breakout": TurtleBreakoutStrategy,
    "vwap_reversion": VwapReversionStrategy,
    "pairs_stat_arb": PairsStatArbStrategy,
    "quality_momentum": QualityMomentumStrategy,
    "insider_cluster": InsiderClusterStrategy,
    "bulk_accumulation": BulkAccumulationStrategy,
    "iv_premium_sell": IvPremiumSellStrategy,
    "cash_futures_basis": CashFuturesBasisStrategy,
    "expiry_gamma": ExpiryGammaStrategy,
    "earnings_vol": EarningsVolStrategy,
    "global_risk_beta": GlobalRiskBetaStrategy,
}


class StrategyRegistry:
    def __init__(self, enabled: Optional[List[str]] = None) -> None:
        ids = enabled or list(_BUILTIN.keys())
        self._strategies: List[Strategy] = []
        for sid in ids:
            cls = _BUILTIN.get(sid)
            if cls:
                self._strategies.append(cls())

    async def dispatch(self, event: MarketEvent, ctx: MarketContext) -> List[Signal]:
        out: List[Signal] = []
        for s in self._strategies:
            if event.type in s.listens_to:
                sig = await s.on_event(event, ctx)
                if sig:
                    out.append(sig)
        return out

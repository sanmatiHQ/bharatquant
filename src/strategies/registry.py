"""Load and run registered strategies."""
from __future__ import annotations

from typing import List, Optional, Type

from ..events.types import EventType, MarketEvent
from .advanced_quant import (
    AdaptiveAlphaStrategy,
    BollingerSqueezeStrategy,
    CrudeEnergyBetaStrategy,
    DualMomentumProStrategy,
    FiiDivergenceStrategy,
    GiftFiiSyncStrategy,
    MacroConfluenceStrategy,
    RsiRegimeAdaptiveStrategy,
    StrategyLabStrategy,
    VwapVolumeConfirmStrategy,
    VolumeBreakoutStrategy,
)
from .base import MarketContext, Signal, Strategy
from .affordable_momentum import AffordableMomentumStrategy
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
from .options_greeks import OptionsGreeksStrategy
from .sector_rotation import SectorRotationStrategy
from .pairs_stat_arb import PairsStatArbStrategy
from .quality_momentum import QualityMomentumStrategy
from .short_term_reversal import ShortTermReversalStrategy
from .stop_loss_guard import StopLossGuardStrategy
from .turtle_breakout import TurtleBreakoutStrategy
from .custom_rules import load_custom_strategies
from .vwap_reversion import VwapReversionStrategy

_BUILTIN: dict[str, Type[Strategy]] = {
    "affordable_momentum": AffordableMomentumStrategy,
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
    "macro_confluence": MacroConfluenceStrategy,
    "gift_fii_sync": GiftFiiSyncStrategy,
    "volume_breakout": VolumeBreakoutStrategy,
    "bollinger_squeeze": BollingerSqueezeStrategy,
    "dual_momentum_pro": DualMomentumProStrategy,
    "fii_divergence": FiiDivergenceStrategy,
    "vwap_volume_confirm": VwapVolumeConfirmStrategy,
    "crude_energy_beta": CrudeEnergyBetaStrategy,
    "rsi_regime_adaptive": RsiRegimeAdaptiveStrategy,
    "adaptive_alpha": AdaptiveAlphaStrategy,
    "strategy_lab": StrategyLabStrategy,
    "sector_rotation": SectorRotationStrategy,
    "options_greeks": OptionsGreeksStrategy,
}


def strategy_count() -> int:
    return len(_BUILTIN)


class StrategyRegistry:
    def __init__(
        self,
        enabled: Optional[List[str]] = None,
        db=None,
        config: Optional[dict] = None,
    ) -> None:
        ids = enabled or list(_BUILTIN.keys())
        self._strategies: List[Strategy] = []
        for sid in ids:
            cls = _BUILTIN.get(sid)
            if not cls:
                continue
            if sid in ("strategy_lab", "sector_rotation", "options_greeks", "pairs_stat_arb", "affordable_momentum"):
                self._strategies.append(cls(db=db))
            else:
                self._strategies.append(cls())
        if config:
            for custom in load_custom_strategies(config):
                self._strategies.append(custom)

    async def dispatch(self, event: MarketEvent, ctx: MarketContext) -> List[Signal]:
        out: List[Signal] = []
        for s in self._strategies:
            if event.type in s.listens_to:
                sig = await s.on_event(event, ctx)
                if sig:
                    out.append(sig)
        return out

    async def dispatch_exits_only(self, event: MarketEvent, ctx: MarketContext) -> List[Signal]:
        """Fast path: stop-loss / exit strategies only — entries via FAST_SNAPSHOT."""
        out: List[Signal] = []
        for s in self._strategies:
            if s.id != "stop_loss_guard":
                continue
            if event.type in s.listens_to:
                sig = await s.on_event(event, ctx)
                if sig:
                    out.append(sig)
        return out

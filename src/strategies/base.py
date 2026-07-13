"""Strategy plugin protocol — register 1..N strategies in config."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from ..events.types import EventType, MarketEvent


@dataclass
class Signal:
    strategy_id: str
    symbol: str
    action: str  # BUY | SELL | HOLD | HEDGE
    rail: str  # CNC | MIS | NRML | OPT
    confidence: float
    reason: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketContext:
    """Mutable session state — unified multimodal state vector source."""
    regime: str = "NEUTRAL"
    gift_nifty_change_pct: float = 0.0
    fii_net_cr: float = 0.0
    dii_net_cr: float = 0.0
    india_vix: float = 0.0
    us_sp_change_pct: float = 0.0
    crude_change_pct: float = 0.0
    usd_inr_change_pct: float = 0.0
    us_vix_chg: float = 0.0
    nikkei_chg: float = 0.0
    hang_seng_chg: float = 0.0
    futures_oi_chg: float = 0.0
    llm_bias: float = 0.0
    llm_sector_bias: dict[str, float] = field(default_factory=dict)
    spread_bps: dict[str, float] = field(default_factory=dict)
    orderbook_imbalance: dict[str, float] = field(default_factory=dict)
    tick_atr_bps: dict[str, float] = field(default_factory=dict)
    orb_high: dict[str, float] = field(default_factory=dict)
    orb_low: dict[str, float] = field(default_factory=dict)
    session_open: dict[str, float] = field(default_factory=dict)
    last_ltp: dict[str, float] = field(default_factory=dict)
    session_vwap: dict[str, float] = field(default_factory=dict)
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    strategy_scores: dict[str, float] = field(default_factory=dict)
    recent_corporate: list[dict[str, Any]] = field(default_factory=list)
    dividend_watch: list[str] = field(default_factory=list)
    promoter_watch: list[str] = field(default_factory=list)
    institutional_weights: dict[str, Any] = field(default_factory=dict)
    strategy_learn_weights: dict[str, Any] = field(default_factory=dict)
    institutional_holdings: list[dict[str, Any]] = field(default_factory=list)
    participant_client_net: float = 0.0
    participant_fii_net: float = 0.0
    participant_dii_net: float = 0.0
    retail_fii_divergence: float = 0.0
    upcoming_events: list[dict[str, Any]] = field(default_factory=list)
    # Market clock (IST)
    session_phase: str = "closed"
    nse_status: str = "Unknown"
    market_open: bool = False
    ist_date: str = ""
    ist_time: str = ""
    minutes_to_close: int = 0
    minutes_from_open: int = 0
    is_expiry_day: bool = False
    is_weekend: bool = False
    # Sentiment / news
    fear_greed_index: float = 50.0
    sentiment_label: str = "Neutral"
    recent_headlines: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class Strategy(Protocol):
    id: str
    listens_to: set[EventType]

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        ...

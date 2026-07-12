"""Market event types — triggers for all trading decisions."""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any


class EventType(enum.StrEnum):
    # GIFT Nifty (signal only — NSE IX)
    GIFT_TICK = "GIFT_TICK"
    GIFT_SESSION_CHANGE = "GIFT_SESSION_CHANGE"

    # NSE session lifecycle (from exchange status, not wall clock)
    SESSION_PRE_OPEN = "SESSION_PRE_OPEN"
    SESSION_OPEN = "SESSION_OPEN"
    SESSION_CLOSE = "SESSION_CLOSE"
    PREOPEN_PRICE = "PREOPEN_PRICE"
    BLOCK_DEAL = "BLOCK_DEAL"

    # Kite WebSocket
    TICK = "TICK"
    BAR_CLOSE_5M = "BAR_CLOSE_5M"
    BAR_CLOSE_15M = "BAR_CLOSE_15M"
    BAR_CLOSE_1D = "BAR_CLOSE_1D"
    ORDER_FILL = "ORDER_FILL"
    FEED_RECONNECT = "FEED_RECONNECT"

    # Institutional / NSE public
    FII_DII_UPDATE = "FII_DII_UPDATE"
    INSIDER_FILING = "INSIDER_FILING"
    IV_UPDATE = "IV_UPDATE"
    NEWS_ALERT = "NEWS_ALERT"

    # Derived risk
    STOP_BREACH = "STOP_BREACH"
    TAKE_PROFIT = "TAKE_PROFIT"
    VOLUME_ANOMALY = "VOLUME_ANOMALY"
    VWAP_CROSS = "VWAP_CROSS"

    # Auth / ops
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    WS_AUTH_FAIL = "WS_AUTH_FAIL"
    FEED_STALE = "FEED_STALE"


@dataclass(frozen=True)
class MarketEvent:
    type: EventType
    symbol: str = ""
    price: float = 0.0
    ts: int = field(default_factory=lambda: int(time.time()))
    payload: dict[str, Any] = field(default_factory=dict)

"""User-defined rule strategies from config — no code deploy needed."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy

_EVENT_MAP = {
    "TICK": EventType.TICK,
    "BAR_CLOSE_5M": EventType.BAR_CLOSE_5M,
    "BAR_CLOSE_15M": EventType.BAR_CLOSE_15M,
    "VWAP_CROSS": EventType.VWAP_CROSS,
    "GIFT_TICK": EventType.GIFT_TICK,
    "FII_DII_UPDATE": EventType.FII_DII_UPDATE,
    "SESSION_OPEN": EventType.SESSION_OPEN,
}


@dataclass
class CustomRuleSpec:
    id: str
    listens: Set[EventType]
    conditions: Dict[str, float]
    action: str
    rail: str
    confidence: float
    reason: str


def _check_conditions(p: dict, ctx: MarketContext, conditions: Dict[str, float]) -> bool:
    ctx_vals = {
        "fii_net_cr": ctx.fii_net_cr,
        "gift_nifty_change_pct": ctx.gift_nifty_change_pct,
        "india_vix": ctx.india_vix,
        "us_sp_change_pct": ctx.us_sp_change_pct,
        "crude_change_pct": ctx.crude_change_pct,
    }
    for key, threshold in conditions.items():
        if key.endswith("_gt"):
            field = key[:-3]
            val = float(p.get(field, ctx_vals.get(field, 0)) or 0)
            if val <= threshold:
                return False
        elif key.endswith("_lt"):
            field = key[:-3]
            val = float(p.get(field, ctx_vals.get(field, 0)) or 0)
            if val >= threshold:
                return False
        elif key.endswith("_gte"):
            field = key[:-4]
            val = float(p.get(field, ctx_vals.get(field, 0)) or 0)
            if val < threshold:
                return False
    return True


class CustomRuleStrategy:
    """Evaluates a single YAML-defined rule set."""

    def __init__(self, spec: CustomRuleSpec) -> None:
        self.id = spec.id
        self.listens_to = spec.listens
        self._spec = spec

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        sym = (event.symbol or "").replace("NSE:", "")
        if not sym and self._spec.action != "HEDGE":
            return None
        p = event.payload or {}
        if not _check_conditions(p, ctx, self._spec.conditions):
            return None
        target = sym or "NIFTYBEES"
        return Signal(
            self.id,
            target,
            self._spec.action,
            self._spec.rail,
            self._spec.confidence,
            self._spec.reason,
        )


def load_custom_strategies(config: dict) -> List[Strategy]:
    """Parse config['custom_strategies'] into runnable strategy instances."""
    specs_raw = config.get("custom_strategies") or []
    out: List[Strategy] = []
    for raw in specs_raw:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        listens = set()
        for name in raw.get("listens", ["BAR_CLOSE_5M"]):
            ev = _EVENT_MAP.get(str(name).upper())
            if ev:
                listens.add(ev)
        if not listens:
            continue
        spec = CustomRuleSpec(
            id=str(raw["id"]),
            listens=listens,
            conditions={k: float(v) for k, v in (raw.get("conditions") or {}).items()},
            action=str(raw.get("action", "BUY")).upper(),
            rail=str(raw.get("rail", "MIS")).upper(),
            confidence=float(raw.get("confidence", 0.65)),
            reason=str(raw.get("reason", "custom_rule")),
        )
        out.append(CustomRuleStrategy(spec))
    return out

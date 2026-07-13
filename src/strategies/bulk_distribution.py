"""Follow institutional distribution (bulk/block sells)."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from ..intelligence.corporate_activity import normalize_bulk
from ..intelligence.institutional_entities import classify_entity, entity_confidence_boost
from .base import MarketContext, Signal, Strategy


class BulkDistributionStrategy:
    id = "bulk_distribution"
    listens_to = {EventType.BLOCK_DEAL}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        p = event.payload or {}
        side_raw = str(p.get("buySell", p.get("side", ""))).lower()
        if "sell" not in side_raw and "disposal" not in side_raw:
            return None
        qty = float(p.get("qty", p.get("quantity", 0)) or 0)
        if qty < 100_000:
            return None
        sym = event.symbol.replace("NSE:", "") or str(p.get("symbol", "")).replace("NSE:", "")
        if not sym:
            return None
        norm = normalize_bulk(p)
        entity = norm.get("entity_class") or classify_entity(str(norm.get("client", "")))
        conf = 0.62 + entity_confidence_boost(entity, "sell")
        weights = getattr(ctx, "institutional_weights", {}) or {}
        strat_w = float((weights.get("strategies") or {}).get(self.id, 1.0))
        conf = min(0.88, conf * strat_w)
        return Signal(
            self.id,
            sym,
            "SELL",
            "CNC",
            conf,
            norm.get("reason", f"institutional_sell_{int(qty)}"),
            meta={"entity_class": entity, "kind": "distribution"},
        )

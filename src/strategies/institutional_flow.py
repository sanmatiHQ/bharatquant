"""MF / shareholding pattern increases — quarterly institutional accumulation."""
from __future__ import annotations

from typing import Optional

from ..events.types import EventType, MarketEvent
from .base import MarketContext, Signal, Strategy


class InstitutionalFlowStrategy:
    id = "institutional_flow"
    listens_to = {EventType.SHAREHOLDING_UPDATE, EventType.MF_HOLDING_UPDATE}

    async def on_event(self, event: MarketEvent, ctx: MarketContext) -> Optional[Signal]:
        p = event.payload or {}
        sym = event.symbol.replace("NSE:", "") or str(p.get("symbol", "")).replace("NSE:", "")
        if not sym:
            return None

        if event.type == EventType.SHAREHOLDING_UPDATE:
            deltas = p.get("deltas") or {}
            mf_delta = float(deltas.get("mf_pct") or deltas.get("institutional_pct") or 0)
            fii_delta = float(deltas.get("fii_pct") or 0)
            pub_delta = float(deltas.get("public_pct") or 0)
            prom_delta = float(deltas.get("promoter_pct") or 0)
            if mf_delta < 0.25 and fii_delta < 0.25 and pub_delta < 0.25 and prom_delta < 0.25:
                return None
            if prom_delta >= max(mf_delta, pub_delta, fii_delta) and prom_delta >= 0.25:
                driver = "promoter_up"
                delta = prom_delta
            elif pub_delta >= mf_delta:
                driver = "public_inst_up"
                delta = pub_delta
            else:
                driver = "mf_up" if mf_delta >= fii_delta else "fii_up"
                delta = max(mf_delta, fii_delta)
            conf = min(0.82, 0.58 + delta * 0.08)
            reason = (
                f"Shareholding {driver}: promoter {prom_delta:+.2f}%, "
                f"public {pub_delta:+.2f}%, inst-proxy {mf_delta:+.2f}% QoQ"
            )
        else:
            side = str(p.get("side", "buy")).lower()
            if side != "buy":
                return None
            qty = float(p.get("qty", 0) or 0)
            client = str(p.get("client", "MF"))
            conf = 0.65 if qty >= 50_000 else 0.58
            reason = f"MF flow {client} buy {int(qty):,} shares"

        weights = getattr(ctx, "institutional_weights", {}) or {}
        strat_w = float((weights.get("strategies") or {}).get(self.id, 1.0))
        conf = min(0.9, conf * strat_w)
        return Signal(self.id, sym, "BUY", "CNC", conf, reason, meta={"entity_class": "mf"})

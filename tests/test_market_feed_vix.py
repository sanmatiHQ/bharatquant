"""VIX fallback must not store change pct as level."""
from __future__ import annotations

from src.ingest.market_feed_client import fetch_global_macro_bundle


def test_vix_fallback_stores_change_not_level(monkeypatch):
    monkeypatch.setattr(
        "src.ingest.market_feed_client.fetch_kite_snapshot",
        lambda: {},
    )
    monkeypatch.setattr(
        "src.ingest.market_feed_client.fetch_yahoo_chart_change_pct",
        lambda sym, **kw: 12.5 if "INDIAVIX" in sym else None,
    )
    bundle = fetch_global_macro_bundle()
    assert "india_vix" not in bundle
    assert bundle.get("india_vix_change_pct") == 12.5

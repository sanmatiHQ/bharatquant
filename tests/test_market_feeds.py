from __future__ import annotations

import pytest

from src.ingest.market_feed_client import (
    fetch_global_macro_bundle,
    fetch_nse_fii_dii,
    fetch_nse_market_status,
    fetch_yahoo_chart_change_pct,
)


@pytest.mark.integration
def test_nse_gift_nifty_live():
    row = fetch_nse_market_status()
    assert row["gift_last"] > 0
    assert "gift_change_pct" in row
    assert row["source"] == "nse.marketStatus.giftnifty"


@pytest.mark.integration
def test_nse_fii_dii_live():
    row = fetch_nse_fii_dii()
    assert "fii_net" in row
    assert row.get("date")


@pytest.mark.integration
def test_yahoo_chart_es_futures():
    chg = fetch_yahoo_chart_change_pct("ES=F")
    assert chg is not None


@pytest.mark.integration
def test_global_macro_bundle_live():
    bundle = fetch_global_macro_bundle()
    assert bundle
    assert "india_vix" in bundle or "us_sp" in bundle

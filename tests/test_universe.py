"""Tests for full NSE universe builder."""
from __future__ import annotations

from src.data.universe_builder import UniverseConfig, filter_nse_equities, fetch_instruments_csv


def test_main_tier_has_thousands():
    df = fetch_instruments_csv()
    out = filter_nse_equities(df, UniverseConfig(tier="main"))
    assert len(out) >= 2000


def test_with_sme_larger_than_main():
    df = fetch_instruments_csv()
    main = filter_nse_equities(df, UniverseConfig(tier="main"))
    sme = filter_nse_equities(df, UniverseConfig(tier="with_sme"))
    assert len(sme) > len(main)


def test_universe_csv_on_disk():
    from pathlib import Path

    p = Path("data/universe_full_nse.csv")
    assert p.exists()
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2000  # header + symbols

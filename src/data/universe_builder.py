"""
Build NSE equity universe from Kite public instruments CSV (no auth required).

Tiers:
  main     — all main-board EQ (no series suffix), ~2,700 symbols
  with_sme — main + SME (-SM), ~3,100 symbols
  all_eq   — every NSE EQ minus ETFs/debt/prefs (~9k; includes illiquid series)

CLI:
  python3.11 -m src.data.universe_builder --tier main
  python3.11 -m src.data.universe_builder --tier with_sme --out data/universe_full_nse_sme.csv
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
import pandas as pd

logger = logging.getLogger("bharatquant.universe")

KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments"

# Debt / govt / trade-to-trade series — not cash-market momentum targets
_EXCLUDED_SUFFIXES = {
    "SG", "GS", "GB", "SF", "TB", "IV", "ND", "NA", "BZ", "BE", "ST",
    "N0", "N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9",
}

Tier = Literal["main", "with_sme", "all_eq"]


@dataclass
class UniverseConfig:
    tier: Tier = "main"
    min_last_price: float = 0.0  # instruments dump has last_price=0; filter at screener runtime
    exclude_etf: bool = True


def fetch_instruments_csv() -> pd.DataFrame:
    """Public Kite master — no API key needed."""
    with httpx.Client(timeout=60.0) as client:
        r = client.get(KITE_INSTRUMENTS_URL)
        r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    if "tradingsymbol" not in df.columns and "trading_symbol" in df.columns:
        df = df.rename(columns={"trading_symbol": "tradingsymbol"})
    return df


def _suffix(symbol: str) -> str | None:
    m = re.search(r"-([A-Z0-9]+)$", symbol)
    return m.group(1) if m else None


def filter_nse_equities(df: pd.DataFrame, cfg: UniverseConfig) -> pd.DataFrame:
    eq = df[(df.get("segment") == "NSE") & (df.get("instrument_type") == "EQ")].copy()
    if eq.empty:
        raise RuntimeError("No NSE EQ rows in instruments dump")
    eq = eq.reset_index(drop=True)

    ts = eq["tradingsymbol"].astype(str)
    nm = eq.get("name", pd.Series([""] * len(eq), index=eq.index)).astype(str)

    if cfg.exclude_etf:
        etf = ts.str.contains(r"ETF|BEES", case=False, na=False) | nm.str.contains(
            r"ETF|BEES|INDEX", case=False, na=False
        )
        eq = eq.loc[~etf].reset_index(drop=True)
        ts = eq["tradingsymbol"].astype(str)
        nm = eq.get("name", pd.Series([""] * len(eq), index=eq.index)).astype(str)

    pref = nm.str.contains(r"PREF|PREFERENCE", case=False, na=False)
    eq = eq.loc[~pref].reset_index(drop=True)
    ts = eq["tradingsymbol"].astype(str)

    suffixes = ts.map(_suffix)
    main_mask = suffixes.isna()
    sme_mask = suffixes == "SM"

    if cfg.tier == "main":
        eq = eq.loc[main_mask]
    elif cfg.tier == "with_sme":
        eq = eq.loc[main_mask | sme_mask]
    else:  # all_eq
        bad = suffixes.isin(_EXCLUDED_SUFFIXES)
        eq = eq.loc[~bad]

    if "last_price" in eq.columns and cfg.min_last_price > 0:
        lp = pd.to_numeric(eq["last_price"], errors="coerce").fillna(0)
        eq = eq.loc[lp >= cfg.min_last_price]

    return eq.sort_values("tradingsymbol").reset_index(drop=True)


def export_universe(
    out_path: str,
    cfg: UniverseConfig | None = None,
    df: pd.DataFrame | None = None,
) -> int:
    cfg = cfg or UniverseConfig()
    raw = df if df is not None else fetch_instruments_csv()
    filtered = filter_nse_equities(raw, cfg)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Screener + engine read `symbol` or `tradingsymbol`; keep token for offline bootstrap
    export = filtered[
        ["instrument_token", "tradingsymbol", "name", "last_price", "lot_size"]
    ].copy()
    export.insert(0, "symbol", export["tradingsymbol"].map(lambda s: f"NSE:{s}"))
    export.to_csv(out, index=False)
    logger.info("universe_exported", extra={"path": str(out), "count": len(export), "tier": cfg.tier})
    return len(export)


def default_path(tier: Tier) -> str:
    return {
        "main": "data/universe_full_nse.csv",
        "with_sme": "data/universe_full_nse_sme.csv",
        "all_eq": "data/universe_all_nse_eq.csv",
    }[tier]


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Build full NSE equity universe CSV")
    parser.add_argument("--tier", choices=["main", "with_sme", "all_eq"], default="main")
    parser.add_argument("--out", default="", help="Output CSV path")
    parser.add_argument("--min-price", type=float, default=0.0)
    args = parser.parse_args()

    out = args.out or default_path(args.tier)
    cfg = UniverseConfig(tier=args.tier, min_last_price=args.min_price)
    n = export_universe(out, cfg)
    print(f"Exported {n} symbols → {out} (tier={args.tier})")


if __name__ == "__main__":
    main()

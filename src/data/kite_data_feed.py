"""
Zerodha-only data feed: LTP and historical OHLC.

CLI:
  python -m src.data.kite_data_feed --export-full-nse data/universe_full_nse.csv
"""
from __future__ import annotations
import os
import time
import argparse
import io
import json
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd
import requests

from ..utils.logging_setup import get_logger
from ..utils.rate_limit import RateLimiter
from ..utils.backoff import retry


@dataclass
class KiteSession:
    api_key: str
    access_token: str


class KiteDataFeed:
    def __init__(self) -> None:
        self.api_key = os.getenv("KITE_API_KEY")
        token_path = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
        if not self.api_key or not os.path.exists(token_path):
            raise RuntimeError("Kite API key or access token file missing.")
        with open(token_path, "r", encoding="utf-8") as f:
            token_json = json.load(f)
        # Accept either {"access_token": "..."} or {"data": {"access_token": "..."}}
        access_token = token_json.get("access_token")
        if not access_token and isinstance(token_json.get("data"), dict):
            access_token = token_json["data"].get("access_token")
        self.access_token = str(access_token or "").strip()
        self.logger = get_logger("kite_data", logs_dir=os.getenv("LOGS_DIR", "logs"))
        self.rate_limiter = RateLimiter(max_per_sec=3, max_per_min=180)
        self.session = requests.Session()
        self.session.headers.update({
            "X-Kite-Version": "3",
            "User-Agent": "zerodha-momo-rl/1.0",
            "Authorization": f"token {self.api_key}:{self.access_token}",
        })

    def _wait_for_slot(self) -> None:
        while not self.rate_limiter.allow():
            time.sleep(0.05)

    @retry()
    def ltp(self, instruments: List[str]) -> Dict[str, float]:
        """Fetch LTP for a list of instruments like ["NSE:INFY"]."""
        self._wait_for_slot()
        url = "https://api.kite.trade/quote/ltp"
        params = {"i": instruments}
        resp = self.session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()["data"]
        return {k: float(v["last_price"]) for k, v in data.items()}

    @retry()
    def historical(self, instrument_token: int, start: str, end: str, interval: str = "day") -> pd.DataFrame:
        """Fetch historical OHLC; start/end in YYYY-MM-DD format; interval like 'day'."""
        self._wait_for_slot()
        url = f"https://api.kite.trade/instruments/historical/{instrument_token}/{interval}"
        params = {"from": start, "to": end}
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        arr = resp.json()["data"]["candles"]
        cols = ["date", "open", "high", "low", "close", "volume"]
        df = pd.DataFrame(arr, columns=cols)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        return df

    @retry()
    def fetch_instruments(self) -> pd.DataFrame:
        """Download full instruments CSV from Kite and return as DataFrame."""
        self._wait_for_slot()
        url = "https://api.kite.trade/instruments"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        csv_text = resp.text
        df = pd.read_csv(io.StringIO(csv_text))
        # Normalize column names we depend upon
        if "tradingsymbol" not in df.columns and "trading_symbol" in df.columns:
            df = df.rename(columns={"trading_symbol": "tradingsymbol"})
        return df

    def export_full_nse(self, out_path: str) -> int:
        """Export filtered NSE EQ universe to CSV."""
        df = self.fetch_instruments()
        # Ensure expected columns exist; Kite returns many, we subset/rename where available
        required_like = [
            "instrument_token",
            "tradingsymbol",
            "exchange",
            "name",
            "last_price",
            "tick_size",
            "lot_size",
            "expiry",
            "segment",
            "instrument_type",
        ]

        # Filter: NSE equities, exclude ETFs and BE/BL series and obvious prefs
        df = df[(df.get("segment") == "NSE") & (df.get("instrument_type") == "EQ")]
        # Exclusions based on common naming conventions
        ts = df["tradingsymbol"].astype(str)
        nm = df.get("name", "").astype(str)
        mask_etf = ts.str.contains(r"ETF|BEES", case=False, na=False) | nm.str.contains(r"ETF|BEES", case=False, na=False)
        mask_be_bl = ts.str.endswith("-BE", na=False) | ts.str.endswith("-BL", na=False)
        mask_pref = nm.str.contains(r"PREF|PREFERENCE", case=False, na=False)
        df = df[~(mask_etf | mask_be_bl | mask_pref)].copy()

        # Some instrument dumps may miss last_price; keep column with default 0
        for col in required_like:
            if col not in df.columns:
                df[col] = 0 if col == "last_price" else ("" if col in ("expiry", "name") else None)

        out_cols = required_like
        df_out = df[out_cols].copy()
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        df_out.to_csv(out_path, index=False)
        self.logger.info("Universe updated: %d NSE equities loaded.", len(df_out))
        return int(len(df_out))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-full-nse", dest="export_full_nse", metavar="OUT_CSV", help="Export full NSE EQ universe to CSV")
    args = parser.parse_args()

    if args.export_full_nse:
        feed = KiteDataFeed()
        count = feed.export_full_nse(args.export_full_nse)
        print(f"Exported {count} NSE instruments to {args.export_full_nse}")
    else:
        print("No action specified. Use --export-full-nse <out.csv>.")


if __name__ == "__main__":
    main()

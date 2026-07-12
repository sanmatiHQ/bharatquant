"""Test-only mock feed — production must use KiteDataFeed."""
from __future__ import annotations

import io
from datetime import datetime, timedelta

import pandas as pd


class MockKiteFeed:
    """Provides deterministic OHLC for unit tests only."""

    def historical(self, instrument_token: int, start: str, end: str, interval: str = "day") -> pd.DataFrame:
        n = 260
        dates = pd.date_range(end=datetime.utcnow(), periods=n, freq="B")
        close = pd.Series(100.0 + pd.Series(range(n)).mul(0.2).values, index=dates)
        return pd.DataFrame(
            {
                "date": dates,
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 500_000,
            }
        )

    def fetch_instruments(self) -> pd.DataFrame:
        csv = "instrument_token,tradingsymbol,exchange,segment,instrument_type\n1,INFY,NSE,NSE,EQ\n2,TCS,NSE,NSE,EQ\n3,RELIANCE,NSE,NSE,EQ\n"
        return pd.read_csv(io.StringIO(csv))

    def ltp(self, instruments: list[str]) -> dict[str, float]:
        return {k: 1500.0 for k in instruments}

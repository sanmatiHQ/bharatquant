"""
Feature computation and aggregation from OHLC dataframes.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any
import pandas as pd

from .indicators import atr, bb_width_pct, macd, ma_align, pct_ret, rsi


@dataclass
class FeatureStore:
    def compute_features(self, hist_df: pd.DataFrame) -> Dict[str, Any]:
        """Compute feature vector from OHLC dataframe with columns [date, open, high, low, close, volume]."""
        close = hist_df["close"]
        high = hist_df["high"]
        low = hist_df["low"]
        _, _, macd_hist = macd(close)
        feats: Dict[str, Any] = {
            "r1m": float(pct_ret(close, 21).iloc[-1]),
            "r3m": float(pct_ret(close, 63).iloc[-1]),
            "rsi": float(rsi(close).iloc[-1]),
            "ma_align": int(ma_align(close)),
            "atr14": float(atr(high, low, close).iloc[-1]),
            "bb_width_pct": float(bb_width_pct(close)),
            "macd_hist": float(macd_hist.iloc[-1]),
        }
        return feats

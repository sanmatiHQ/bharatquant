"""
Technical indicators and factor helpers.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(gain, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    roll_down = pd.Series(loss, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    rsi_vals = 100 - (100 / (1 + rs))
    return rsi_vals.fillna(50.0)


def pct_ret(series: pd.Series, lookback: int) -> pd.Series:
    return series.pct_change(periods=lookback)


def ma_align(close: pd.Series, short: int = 20, mid: int = 50, long: int = 200) -> int:
    ma_s = close.rolling(short).mean().iloc[-1]
    ma_m = close.rolling(mid).mean().iloc[-1]
    ma_l = close.rolling(long).mean().iloc[-1]
    return int(ma_s > ma_m > ma_l)


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """From shashankvemuri/Finance ta_functions — WMA-smoothed TR."""
    tr0 = (high - low).abs()
    tr1 = (high - close.shift()).abs()
    tr2 = (low - close.shift()).abs()
    tr = pd.concat([tr0, tr1, tr2], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def bbands(close: pd.Series, period: int = 20, nbdev: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + nbdev * std, mid, mid - nbdev * std


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    hist = line - sig
    return line, sig, hist


def bb_width_pct(close: pd.Series, period: int = 20) -> float:
    up, mid, lo = bbands(close, period)
    if mid.iloc[-1] == 0 or np.isnan(mid.iloc[-1]):
        return 0.0
    return float((up.iloc[-1] - lo.iloc[-1]) / mid.iloc[-1] * 100.0)

"""Tests for continuous trading exits and bar momentum features."""
from __future__ import annotations

from collections import deque

import pytest

from src.feeds.bar_aggregator import _momentum_features, _rsi
from src.risk.risk_engine import RiskConfig, RiskEngine


def test_rsi_bounds():
    closes = [100 + i * 0.5 for i in range(20)]
    assert 0 <= _rsi(closes) <= 100


def test_momentum_features_from_bars():
    hist = deque([100.0, 101.0, 102.0, 103.5, 104.0], maxlen=20)
    mom = _momentum_features(hist)
    assert mom["r1m"] > 0
    assert mom["r3m"] > 0
    assert 0 < mom["rsi"] < 100


def test_take_profit_exit():
    eng = RiskEngine(RiskConfig(4, 2, 2000, 8, take_profit_percent=2.0))
    ok, reason = eng.should_exit({"avg_price": 100, "last_price": 103, "open_ts": 0})
    assert ok is True
    assert reason.startswith("take_profit")


def test_trailing_stop_exit():
    eng = RiskEngine(RiskConfig(4, 2, 2000, 8, trailing_stop_percent=1.5))
    ok, reason = eng.should_exit(
        {"avg_price": 100, "last_price": 101.5, "open_ts": 0},
        peak_price=104.0,
    )
    assert ok is True
    assert reason.startswith("trailing_stop")


def test_stop_loss_exit():
    eng = RiskEngine(RiskConfig(4, 2, 2000, 8))
    ok, reason = eng.should_exit({"avg_price": 100, "last_price": 95, "open_ts": 0})
    assert ok is True
    assert reason.startswith("stop_loss")

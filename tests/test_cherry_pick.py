from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.alerts.webhook import build_delivery
from src.costs.cost_engine import CostEngine
from src.data.provenance import tag_payload
from src.features.indicators import atr, bb_width_pct, macd, rsi
from src.portfolio.sizing import inverse_vol_weights, rupee_qty_map


def test_provenance_tags():
    p = tag_payload({"x": 1}, source="test.api", execution_allowed=False)
    assert p["source"] == "test.api"
    assert p["execution_allowed"] is False
    assert "fetched_at" in p


def test_rqalpha_style_min_commission():
    ce = CostEngine(slippage_bps=0, min_commission_inr=20.0)
    small = ce.compute_trade_costs("NSE:INFY", 1, 50.0, "BUY", order_id="o1")
    assert small >= 20.0
    large = ce.compute_trade_costs("NSE:INFY", 100, 500.0, "BUY", order_id="o2")
    assert large > 20.0


def test_finance_indicators_no_yfinance():
    idx = pd.date_range("2024-01-01", periods=60, freq="D")
    close = pd.Series(np.linspace(100, 120, 60), index=idx)
    high = close + 1
    low = close - 1
    assert float(rsi(close).iloc[-1]) > 0
    assert float(atr(high, low, close).iloc[-1]) > 0
    _, _, hist = macd(close)
    assert not np.isnan(hist.iloc[-1])
    assert bb_width_pct(close) >= 0


def test_inverse_vol_weights():
    idx = pd.date_range("2024-01-01", periods=40, freq="D")
    a = pd.Series(np.random.default_rng(0).normal(0, 0.01, 40).cumsum() + 100, index=idx)
    b = pd.Series(np.random.default_rng(1).normal(0, 0.05, 40).cumsum() + 50, index=idx)
    df = pd.DataFrame({"LOWVOL": a, "HIGHVOL": b})
    w = inverse_vol_weights(df, max_names=2)
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert w["LOWVOL"] > w["HIGHVOL"]


def test_rupee_qty_map():
    w = {"A": 0.6, "B": 0.4}
    q = rupee_qty_map(w, {"A": 100.0, "B": 200.0}, 1000.0)
    assert q["A"] >= 1
    assert q["B"] >= 1


def test_webhook_signature():
    body, headers = build_delivery("test.event", {"k": 1}, secret="s3cret")
    assert body["delivery_id"]
    assert headers["X-BharatQuant-Signature"]
    assert json.dumps(body)

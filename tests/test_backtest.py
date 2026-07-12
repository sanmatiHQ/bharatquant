from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest.walk_forward import BacktestConfig, run_walk_forward


def _synthetic_panel(n: int = 260, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    cols = {}
    for name, vol in [("LOWVOL", 0.008), ("HIGHVOL", 0.03), ("MID", 0.015)]:
        rets = rng.normal(0.0005, vol, n)
        cols[name] = 100 * np.cumprod(1 + rets)
    cols["NIFTYBEES"] = 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, n))
    return pd.DataFrame(cols, index=idx)


def test_walk_forward_runs():
    panel = _synthetic_panel()
    result = run_walk_forward(panel, BacktestConfig(daily_budget=500, rebalance_days=21))
    assert len(result.equity_curve) == len(panel)
    assert result.metrics["n_trades"] >= 0
    assert "sharpe" in result.metrics
    assert "benchmark_return_pct" in result.metrics

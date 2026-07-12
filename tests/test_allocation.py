from __future__ import annotations

import numpy as np
import pandas as pd

from src.db.database import DB, DBConfig
from src.portfolio.allocation import compute_allocation, persist_allocation, load_target_qty


def test_compute_allocation_inverse_vol(tmp_path):
    idx = pd.date_range("2024-01-01", periods=40, freq="D")
    calm = pd.Series(100 + np.arange(40) * 0.1, index=idx)
    wild = pd.Series(100 + np.random.default_rng(2).normal(0, 3, 40).cumsum(), index=idx)
    panel = pd.DataFrame({"CALM": calm, "WILD": wild})
    screen = pd.DataFrame(
        [
            {"symbol": "CALM", "score": 0.9, "last_close": float(calm.iloc[-1])},
            {"symbol": "WILD", "score": 0.8, "last_close": float(wild.iloc[-1])},
        ]
    )
    alloc = compute_allocation(
        screen,
        panel,
        max_positions=2,
        daily_budget=1000.0,
        max_rupees_per_trade=1000.0,
    )
    assert len(alloc) == 2
    assert alloc.loc[alloc["symbol"] == "CALM", "weight"].iloc[0] > alloc.loc[
        alloc["symbol"] == "WILD", "weight"
    ].iloc[0]
    assert alloc["target_qty"].sum() >= 2


def test_persist_and_load_qty(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))
    df = pd.DataFrame(
        [
            {"symbol": "INFY", "weight": 0.6, "target_qty": 5, "target_rupees": 600.0, "last_price": 120.0},
            {"symbol": "TCS", "weight": 0.4, "target_qty": 2, "target_rupees": 400.0, "last_price": 200.0},
        ]
    )
    persist_allocation(db, df, run_ts=1700000000)
    assert load_target_qty(db, "INFY") == 5
    assert load_target_qty(db, "NSE:TCS") == 2

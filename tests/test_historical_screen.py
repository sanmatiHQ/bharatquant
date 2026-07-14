"""Historical screen and backfill tests."""
from __future__ import annotations

import time

import pytest

from src.backtest.strategy_screen import StrategyScreenResult, persist_screen_results, screen_strategy
from src.db.database import DB, DBConfig
from src.intelligence.historical_screen import candidacy_priority_multiplier, list_historical_screen
from src.strategies.combined_momentum import CombinedMomentumStrategy


@pytest.fixture
def db(tmp_path):
    return DB(DBConfig(sqlite_path=str(tmp_path / "hist.db")))


def _seed_bars(db: DB, symbol: str = "INFY", n: int = 80) -> None:
    ts = int(time.time()) - n * 300
    for i in range(n):
        close = 100.0 + i * 0.3
        db._conn.execute(
            """
            INSERT INTO bar_log(ts,symbol,interval,open,high,low,close,volume)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (ts + i * 300, symbol, "5m", close, close + 0.5, close - 0.2, close, 1000),
        )
    db._conn.commit()


@pytest.mark.asyncio
async def test_screen_strategy_produces_metrics(db):
    _seed_bars(db)
    strat = CombinedMomentumStrategy()
    res = await screen_strategy(db, strat, ["INFY"], interval="5m", lookback_days=30)
    assert res.strategy_id == "combined_momentum"
    assert res.sample_count >= 0


def test_persist_and_priority(db):
    row = StrategyScreenResult(
        strategy_id="test_strat",
        sample_count=25,
        win_rate=0.6,
        sortino=0.4,
        calmar=0.3,
        max_drawdown_pct=5.0,
        binomial_p=0.02,
        composite=0.35,
        cleared=True,
        status="ok",
        interval="5m",
        lookback_days=365,
    )
    persist_screen_results(db, [row])
    assert candidacy_priority_multiplier(db, "test_strat") > 1.0
    listed = list_historical_screen(db)
    assert listed[0]["strategy_id"] == "test_strat"

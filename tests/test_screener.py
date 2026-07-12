from __future__ import annotations
from src.db.database import DB, DBConfig
from src.screening.momentum_screener import MomentumScreener, ScreenerConfig
from tests.mock_feed import MockKiteFeed


def test_screener_runs(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / 't.db')))
    uni = tmp_path / 'universe.csv'
    uni.write_text('symbol\nINFY\nTCS\nRELIANCE\n')
    scr = MomentumScreener(
        ScreenerConfig(universe_csv=str(uni), min_score=0.0, logs_dir='logs'),
        db,
        feed=MockKiteFeed(),
    )
    df = scr.run()
    assert len(df) >= 1
    assert 'symbol' in df.columns
    assert 'last_close' in df.columns

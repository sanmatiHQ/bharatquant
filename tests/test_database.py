from __future__ import annotations
from src.db.database import DB, DBConfig


def test_migrations_and_crud(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / 't.db')))
    db.add_cash(1, 1000.0, 'seed')
    tid = db.record_trade(2, 'NSE:INFY', 'BUY', 1, 100.0, 100.0, 'test', 1.0, 'NA')
    db.upsert_position('NSE:INFY', 1, 100.0, 100.0, 2)
    db.record_screen(3, [(3, 'NSE:INFY', 1.0, 0.1, 0.3, 55.0, 1)])
    db.snapshot_portfolio(4, 1000.0, 0.0, 1000.0, 0.0, 0.0, 0.0)
    assert tid > 0

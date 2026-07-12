from __future__ import annotations

from src.db.database import DB, DBConfig
from src.ops.daily_pnl import portfolio_state
from src.risk.risk_engine import RiskConfig, RiskEngine


def test_daily_loss_rupees_gate(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))
    db.add_cash(1, 10_000.0, "seed")
    st = portfolio_state(db)
    re = RiskEngine(RiskConfig(4.0, 2.0, 2000.0, 5))
    ok, _ = re.can_open_new(st)
    assert ok
    st["day_loss_rupees"] = 2500.0
    ok, reason = re.can_open_new(st)
    assert not ok
    assert reason == "daily_loss_rupees_gate"


def test_kill_switch_veto(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))
    re = RiskEngine(RiskConfig(4.0, 2.0, 2000.0, 5))
    ok, reason = re.can_open_new({"halted": True, "open_positions": 0, "total_equity": 1000, "day_peak_equity": 1000})
    assert not ok
    assert reason == "kill_switch"

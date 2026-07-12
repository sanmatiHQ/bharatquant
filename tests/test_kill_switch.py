from __future__ import annotations

from src.db.database import DB, DBConfig
from src.ops.kill_switch import clear_halt, halt_status, is_halted, set_halt


def test_kill_switch_roundtrip(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))
    assert not is_halted(db)
    set_halt(db, reason="test")
    assert is_halted(db)
    st = halt_status(db)
    assert st["halted"] is True
    assert st["reason"] == "test"
    clear_halt(db)
    assert not is_halted(db)

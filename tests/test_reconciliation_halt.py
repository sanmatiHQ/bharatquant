"""Reconciliation halt streak tests."""
from __future__ import annotations

import os

from src.db.database import DB, DBConfig
from src.ops.kill_switch import is_halted
from src.ops.reconciliation import _track_mismatch_streak


def test_halt_after_streak_in_live_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("RECONCILE_HALT_AFTER", "2")
    db = DB(DBConfig(sqlite_path=str(tmp_path / "r.db")))
    mismatches = [{"symbol": "INFY", "broker_qty": 5, "internal_qty": 0}]
    _track_mismatch_streak(db, mismatches, repaired=0)
    assert not is_halted(db)
    _track_mismatch_streak(db, mismatches, repaired=0)
    assert is_halted(db)


def test_paper_mode_no_halt(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("RECONCILE_HALT_AFTER", "1")
    db = DB(DBConfig(sqlite_path=str(tmp_path / "p.db")))
    for _ in range(3):
        _track_mismatch_streak(db, [{"symbol": "TCS"}], repaired=0)
    assert not is_halted(db)

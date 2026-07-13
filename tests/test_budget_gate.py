"""Budget gate — 15m approval timeout."""
from __future__ import annotations

import json
import os
import time

import pytest

from src.db.database import DB, DBConfig
from src.ops.budget_gate import (
    KEY_APPROVED_MAX,
    KEY_PENDING,
    KEY_PENDING_TS,
    approve_budget_increase,
    budget_status,
    can_deploy,
    expire_pending_if_stale,
    request_budget_increase,
)


@pytest.fixture
def db(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "t.db")
    os.environ["BUDGET_APPROVAL_TIMEOUT_SEC"] = "900"
    return DB(DBConfig(sqlite_path=str(tmp_path / "t.db")))


def test_pending_expires_after_15m(db):
    request_budget_increase(db, 3000, "need more")
    ts = str(int(time.time()) - 901)
    db._conn.execute(
        "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (KEY_PENDING_TS, ts),
    )
    db._conn.commit()
    assert expire_pending_if_stale(db) is True
    assert budget_status(db)["pending_increase"] is None


def test_can_deploy_after_expiry_not_blocked_by_pending(db):
    request_budget_increase(db, 3000, "need more")
    db._conn.execute(
        "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (KEY_PENDING_TS, str(int(time.time()) - 1000)),
    )
    db._conn.commit()
    ok, reason = can_deploy(db, 500)
    assert reason != "budget_exceeded_pending_approval"
    assert budget_status(db)["pending_increase"] is None


def test_rollover_accumulate(db):
    os.environ["BUDGET_ROLLOVER_MODE"] = "accumulate"
    from src.ops.budget_gate import (
        KEY_ROLLED,
        effective_daily_max,
        rollover_at_session_close,
        set_setting,
    )

    set_setting(db, KEY_ROLLED, "2000")
    set_setting(db, KEY_APPROVED_MAX, "2000")
    db._conn.execute(
        "INSERT INTO trades(ts,symbol,side,qty,price,amount) VALUES (?,?,?,?,?,?)",
        (int(time.time()), "INFY", "BUY", 1, 1100, 1100),
    )
    db._conn.commit()
    r = rollover_at_session_close(db)
    assert r["pool_remaining"] == 900.0
    assert effective_daily_max(db) == 900.0


def test_daily_stipend_stacks(db):
    os.environ["BUDGET_ROLLOVER_MODE"] = "accumulate"
    os.environ["DAILY_INVESTMENT_MAX"] = "2000"
    from src.ops.budget_gate import KEY_ROLLED, credit_daily_stipend_on_open, set_setting

    set_setting(db, KEY_ROLLED, "76")
    first = credit_daily_stipend_on_open(db)
    assert first["credited"] == 2000.0
    assert first["pool"] == 2076.0
    second = credit_daily_stipend_on_open(db)
    assert second.get("already_done") is True


def test_strict_no_rollover(db):
    os.environ["BUDGET_ROLLOVER_MODE"] = "strict"
    from src.ops.budget_gate import effective_daily_max, rollover_at_session_close

    r = rollover_at_session_close(db)
    assert r["mode"] == "strict"
    assert effective_daily_max(db) == 2000.0

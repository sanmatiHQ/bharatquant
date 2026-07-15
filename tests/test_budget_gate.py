"""Budget gate — 15m approval timeout."""
from __future__ import annotations

import asyncio
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


# --- TOCTOU race reproduction: two concurrent handlers, one ₹2000 cap ---
# Reproduces the 178% overspend seen in production (deployed_today_inr=3568 vs
# a ~2000-2407 cap): two near-simultaneous BUYs each call can_deploy() while
# deployed_today_inr() is still 0, both see the full cap as "remaining", both
# pass, both record_trade — total deployed exceeds the cap.


async def _unguarded_deploy(db, ts, symbol, amount):
    """Old pattern: check, then (after a yield simulating I/O) record — no shared lock."""
    ok, _ = can_deploy(db, amount)
    if not ok:
        return False
    await asyncio.sleep(0)  # yield control, exactly where the race window sits
    db.record_trade(ts, symbol, "BUY", 1, amount, amount, "test", 0.0, "NA")
    return True


async def _guarded_deploy(db, lock, ts, symbol, amount):
    """Fixed pattern: check + record serialized under one lock, re-checked inside it."""
    async with lock:
        ok, _ = can_deploy(db, amount)
        if not ok:
            return False
        await asyncio.sleep(0)
        db.record_trade(ts, symbol, "BUY", 1, amount, amount, "test", 0.0, "NA")
        return True


def test_unguarded_concurrent_deploys_overspend_cap(db):
    """RED: demonstrates the bug — reproduces it on the old (unguarded) pattern."""
    os.environ["BUDGET_ROLLOVER_MODE"] = "strict"
    os.environ["DAILY_INVESTMENT_MAX"] = "2000"
    ts = int(time.time())

    async def run():
        results = await asyncio.gather(
            _unguarded_deploy(db, ts, "PPAP", 1770.0),
            _unguarded_deploy(db, ts, "PPAP", 1770.0),
        )
        return results

    results = asyncio.run(run())
    assert results == [True, True]  # both "passed" the check — this is the bug
    deployed = float(
        db._conn.execute(
            "SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY' AND ts >= ?",
            (ts - 1,),
        ).fetchone()[0]
    )
    assert deployed == pytest.approx(3540.0)
    assert deployed > 2000.0  # confirmed: overspent the ₹2000 cap


def test_guarded_concurrent_deploys_respect_cap(db):
    """GREEN: the fix — same race, but check+record serialized under one lock."""
    os.environ["BUDGET_ROLLOVER_MODE"] = "strict"
    os.environ["DAILY_INVESTMENT_MAX"] = "2000"
    ts = int(time.time())
    lock = asyncio.Lock()

    async def run():
        results = await asyncio.gather(
            _guarded_deploy(db, lock, ts, "PPAP", 1770.0),
            _guarded_deploy(db, lock, ts, "PPAP", 1770.0),
        )
        return results

    results = asyncio.run(run())
    assert sorted(results) == [False, True]  # only one of the two can fit under the cap
    deployed = float(
        db._conn.execute(
            "SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY' AND ts >= ?",
            (ts - 1,),
        ).fetchone()[0]
    )
    assert deployed == pytest.approx(1770.0)
    assert deployed <= 2000.0  # cap respected

"""Daily deploy budget — hard cap, no auto top-up; optional user approval with 15m timeout."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..db.database import DB

IST = timezone(timedelta(hours=5, minutes=30))

KEY_APPROVED_MAX = "daily_budget_max_approved"
KEY_PENDING = "budget_increase_pending"
KEY_PENDING_TS = "budget_increase_requested_at"
KEY_ROLLED = "budget_rolled_inr"
KEY_LAST_ROLLOVER_DAY = "budget_last_rollover_day"
KEY_STIPEND_DAY = "budget_stipend_credited_day"
KEY_LAST_EXPIRED = "budget_increase_last_expired"


def rollover_mode() -> str:
    """strict = use today's ₹ envelope only (unused lost). accumulate = roll unused to tomorrow."""
    return os.getenv("BUDGET_ROLLOVER_MODE", "strict").lower()


def _ist_today_str() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def rolled_balance_inr(db: DB) -> float:
    if rollover_mode() != "accumulate":
        return 0.0
    raw = get_setting(db, KEY_ROLLED)
    return float(raw) if raw else 0.0


def effective_daily_max(db: DB) -> float:
    """Today's deploy ceiling — persistent pool (accumulate) or daily base (strict)."""
    if rollover_mode() == "accumulate":
        pool = rolled_balance_inr(db)
        return pool if pool > 0 else approved_daily_max(db)
    return approved_daily_max(db)


def credit_daily_stipend_on_open(db: DB) -> dict[str, Any]:
    """
    accumulate: each IST session open adds DAILY_INVESTMENT_MAX to deploy pool (stacks, never resets).
    Example: ₹76 left + fresh ₹2000 tomorrow → ₹2076 deployable.
    """
    if rollover_mode() != "accumulate":
        return {"mode": "strict", "credited": 0.0}
    today = _ist_today_str()
    if get_setting(db, KEY_STIPEND_DAY) == today:
        return {"mode": "accumulate", "credited": 0.0, "pool": rolled_balance_inr(db), "already_done": True}
    stipend = _env_max()
    pool = rolled_balance_inr(db) + stipend
    set_setting(db, KEY_ROLLED, str(round(pool, 2)))
    set_setting(db, KEY_STIPEND_DAY, today)
    return {"mode": "accumulate", "credited": stipend, "pool": pool}


def rollover_at_session_close(db: DB) -> dict[str, Any]:
    """
    accumulate: persist unused deploy pool for next session (then morning stipend adds on top).
    strict: no roll — finish today or lose unused allocation.
    """
    if rollover_mode() != "accumulate":
        return {"mode": "strict", "rolled_added": 0.0, "rolled_total": 0.0}
    today = _ist_today_str()
    if get_setting(db, KEY_LAST_ROLLOVER_DAY) == today:
        return {"mode": "accumulate", "rolled_added": 0.0, "rolled_total": rolled_balance_inr(db), "already_done": True}
    remaining = max(0.0, effective_daily_max(db) - deployed_today_inr(db))
    set_setting(db, KEY_ROLLED, str(round(remaining, 2)))
    set_setting(db, KEY_LAST_ROLLOVER_DAY, today)
    return {"mode": "accumulate", "rolled_added": 0.0, "rolled_total": remaining, "pool_remaining": remaining}


def consume_rolled_on_deploy(db: DB, amount_inr: float) -> None:
    """When deploy exceeds today's fresh base max, deduct overflow from rolled pool."""
    if rollover_mode() != "accumulate" or amount_inr <= 0:
        return
    base = approved_daily_max(db)
    deployed_before = deployed_today_inr(db) - amount_inr
    overflow = max(0.0, deployed_before + amount_inr - base)
    if overflow <= 0:
        return
    rolled = rolled_balance_inr(db)
    set_setting(db, KEY_ROLLED, str(round(max(0.0, rolled - overflow), 2)))


def _approval_timeout_sec() -> int:
    return int(os.getenv("BUDGET_APPROVAL_TIMEOUT_SEC", "900"))  # 15 minutes


def _today_start_ts() -> int:
    now = datetime.now(IST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def _env_min() -> float:
    return float(os.getenv("DAILY_INVESTMENT_MIN", "1500"))


def _env_max() -> float:
    return float(os.getenv("DAILY_INVESTMENT_MAX", "2000"))


def get_setting(db: DB, key: str) -> Optional[str]:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    return str(row["v"]) if row else None


def set_setting(db: DB, key: str, value: str) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (key, value),
        )


def approved_daily_max(db: DB) -> float:
    """User-approved ceiling — never exceeds env max unless explicitly raised via dashboard."""
    raw = get_setting(db, KEY_APPROVED_MAX)
    if raw:
        return min(float(raw), _env_max() * 2)  # safety cap at 2x env
    return _env_max()


def deployed_today_inr(db: DB) -> float:
    today = _today_start_ts()
    return float(
        db._conn.execute(
            "SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY' AND ts >= ?",
            (today,),
        ).fetchone()[0]
    )


def remaining_budget(db: DB) -> float:
    return max(0.0, effective_daily_max(db) - deployed_today_inr(db))


def expire_pending_if_stale(db: DB) -> bool:
    """
    If user did not approve within BUDGET_APPROVAL_TIMEOUT_SEC, drop the request.
    Agent continues with whatever budget/cash remains today — no waiting.
    """
    pending_raw = get_setting(db, KEY_PENDING)
    if not pending_raw:
        return False
    ts_raw = get_setting(db, KEY_PENDING_TS)
    if not ts_raw or not str(ts_raw).isdigit():
        set_setting(db, KEY_PENDING, "")
        set_setting(db, KEY_PENDING_TS, "")
        return True
    age = int(time.time()) - int(ts_raw)
    if age < _approval_timeout_sec():
        return False
    try:
        pending = json.loads(pending_raw)
    except json.JSONDecodeError:
        pending = {}
    set_setting(
        db,
        KEY_LAST_EXPIRED,
        json.dumps(
            {
                "expired_at": int(time.time()),
                "pending": pending,
                "message": "User did not respond in 15m — agent trades with remaining budget only",
            }
        ),
    )
    set_setting(db, KEY_PENDING, "")
    set_setting(db, KEY_PENDING_TS, "")
    return True


def _pending_with_ttl(db: DB) -> tuple[Optional[dict], Optional[int]]:
    expire_pending_if_stale(db)
    pending_raw = get_setting(db, KEY_PENDING)
    if not pending_raw:
        return None, None
    try:
        pending = json.loads(pending_raw)
    except json.JSONDecodeError:
        return None, None
    ts_raw = get_setting(db, KEY_PENDING_TS)
    expires_in = None
    if ts_raw and str(ts_raw).isdigit():
        expires_in = max(0, _approval_timeout_sec() - (int(time.time()) - int(ts_raw)))
    return pending, expires_in


def budget_status(db: DB) -> dict[str, Any]:
    deployed = deployed_today_inr(db)
    approved = approved_daily_max(db)
    effective = effective_daily_max(db)
    pending, expires_in = _pending_with_ttl(db)
    last_expired = None
    raw_exp = get_setting(db, KEY_LAST_EXPIRED)
    if raw_exp:
        try:
            last_expired = json.loads(raw_exp)
        except json.JSONDecodeError:
            last_expired = None
    return {
        "daily_min_inr": _env_min(),
        "daily_max_inr": effective,
        "daily_base_inr": approved,
        "rolled_inr": rolled_balance_inr(db),
        "rollover_mode": rollover_mode(),
        "env_max_inr": _env_max(),
        "deployed_today_inr": deployed,
        "remaining_inr": max(0.0, effective - deployed),
        "budget_used_pct": round(deployed / effective * 100, 1) if effective else 0,
        "pending_increase": pending,
        "pending_ts": get_setting(db, KEY_PENDING_TS),
        "pending_expires_in_sec": expires_in,
        "approval_timeout_sec": _approval_timeout_sec(),
        "last_expired_request": last_expired,
    }


def can_deploy(db: DB, amount_inr: float) -> tuple[bool, str]:
    expire_pending_if_stale(db)
    if amount_inr <= 0:
        return False, "zero_amount"
    remaining = remaining_budget(db)
    if amount_inr <= remaining + 0.01:
        return True, "ok"
    pending = get_setting(db, KEY_PENDING)
    if pending:
        return False, "budget_exceeded_pending_approval"
    return False, f"daily_budget_cap remaining=₹{remaining:.0f} need=₹{amount_inr:.0f}"


def budget_audit_context(db: DB, amount_inr: float = 0.0) -> dict[str, Any]:
    """Structured budget snapshot for veto logging and dashboard audit."""
    st = budget_status(db)
    return {
        "effective_max_inr": st["daily_max_inr"],
        "approved_max_inr": st["daily_base_inr"],
        "rolled_inr": st["rolled_inr"],
        "deployed_today_inr": st["deployed_today_inr"],
        "remaining_inr": st["remaining_inr"],
        "requested_inr": amount_inr,
        "rollover_mode": st["rollover_mode"],
    }


def request_budget_increase(db: DB, requested_max: float, reason: str) -> dict[str, Any]:
    """Agent requests higher daily limit — user has 15m to approve or request auto-expires."""
    expire_pending_if_stale(db)
    current = approved_daily_max(db)
    if requested_max <= current:
        return {"ok": False, "error": "requested_not_higher_than_current"}
    existing = get_setting(db, KEY_PENDING)
    if existing:
        return {"ok": True, "pending": json.loads(existing), "already_pending": True}
    payload = {
        "current_max": current,
        "requested_max": requested_max,
        "reason": reason,
        "deployed_today": deployed_today_inr(db),
        "expires_in_sec": _approval_timeout_sec(),
    }
    set_setting(db, KEY_PENDING, json.dumps(payload))
    set_setting(db, KEY_PENDING_TS, str(int(time.time())))
    return {"ok": True, "pending": payload}


def approve_budget_increase(db: DB, new_max: Optional[float] = None) -> dict[str, Any]:
    expire_pending_if_stale(db)
    pending_raw = get_setting(db, KEY_PENDING)
    if not pending_raw:
        if new_max is None:
            return {"ok": False, "error": "no_pending_request"}
        approved = float(new_max)
    else:
        pending = json.loads(pending_raw)
        approved = float(new_max or pending.get("requested_max", _env_max()))
    approved = max(_env_min(), min(approved, _env_max() * 2))
    set_setting(db, KEY_APPROVED_MAX, str(approved))
    set_setting(db, KEY_PENDING, "")
    set_setting(db, KEY_PENDING_TS, "")
    return {"ok": True, "approved_max": approved}


def reject_budget_increase(db: DB) -> dict[str, Any]:
    set_setting(db, KEY_PENDING, "")
    set_setting(db, KEY_PENDING_TS, "")
    return {"ok": True}


def auto_approve_budget_if_vix_safe(db: DB) -> dict[str, Any]:
    """
    Pre-market safety gate — auto-approve daily deploy cap when India VIX is within limits.
    Clears stale pending increase requests when safe.
    """
    from .vix_controls import vix_from_db, vix_safe_for_budget

    vix = vix_from_db(db)
    if not vix_safe_for_budget(vix):
        return {"ok": False, "reason": f"vix_out_of_range_{vix:.1f}", "vix": vix}
    approved = _env_max()
    set_setting(db, KEY_APPROVED_MAX, str(approved))
    set_setting(db, KEY_PENDING, "")
    set_setting(db, KEY_PENDING_TS, "")
    return {"ok": True, "approved_max": approved, "vix": vix, "auto": True}

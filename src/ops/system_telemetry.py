"""Infrastructure telemetry — Kite latency, VM load, slippage risk, circuit breakers."""
from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any

import httpx

from ..db.database import DB
from ..ops.healthchecks import check_db, check_token
from ..ops.kill_switch import halt_status, is_halted
from ..ops.slumber_mode import slumber_status

_ping_cache: dict[str, Any] = {"ts": 0, "latency_ms": None}


def _kite_ping_ms() -> float | None:
    """Cached Kite REST round-trip (ms)."""
    now = time.time()
    if now - _ping_cache["ts"] < 30 and _ping_cache["latency_ms"] is not None:
        return _ping_cache["latency_ms"]
    path = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        token = data.get("access_token") or (data.get("data") or {}).get("access_token")
        api_key = os.getenv("KITE_API_KEY", "")
        if not token or not api_key:
            return None
        t0 = time.perf_counter()
        r = httpx.get(
            "https://api.kite.trade/user/profile",
            headers={"X-Kite-Version": "3", "Authorization": f"token {api_key}:{token}"},
            timeout=2.0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            _ping_cache.update({"ts": now, "latency_ms": round(ms, 1)})
            return _ping_cache["latency_ms"]
    except Exception:
        pass
    # Return last good ping instead of blocking feed on slow Kite responses
    if _ping_cache.get("latency_ms") is not None:
        return _ping_cache["latency_ms"]
    return None


def _vm_load() -> dict[str, float | None]:
    try:
        import psutil

        return {
            "cpu_pct": round(psutil.cpu_percent(interval=0.1), 1),
            "ram_pct": round(psutil.virtual_memory().percent, 1),
            "disk_pct": round(psutil.disk_usage("/").percent, 1),
        }
    except ImportError:
        load = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
        return {"cpu_pct": round(load * 10, 1) if load else None, "ram_pct": None, "disk_pct": None}


def _max_drawdown_today(db: DB) -> float:
    today = int(time.time()) - (int(time.time()) % 86400)
    rows = db._conn.execute(
        "SELECT total_value FROM portfolio_history WHERE ts >= ? ORDER BY ts ASC",
        (today,),
    ).fetchall()
    if len(rows) < 2:
        return 0.0
    peak = float(rows[0]["total_value"])
    max_dd = 0.0
    for r in rows:
        v = float(r["total_value"])
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak * 100)
    return round(max_dd, 2)


def build_system_telemetry(db: DB, *, ws_live: bool = False, engine_live: bool = False) -> dict[str, Any]:
    kite_ms = _kite_ping_ms()
    load = _vm_load()
    halt = halt_status(db)
    slumber = slumber_status(db)
    latency_warn = float(os.getenv("TELEMETRY_LATENCY_WARN_MS", "400"))
    high_slippage_risk = kite_ms is not None and kite_ms > latency_warn

    kite_ring = "green"
    if not check_token(live=True):
        kite_ring = "red"
    elif high_slippage_risk:
        kite_ring = "orange"
    elif kite_ms is None:
        kite_ring = "orange"

    llm_ring = "green"
    llm_ts_row = db._conn.execute("SELECT v FROM settings WHERE k='llm_macro_updated_ts'").fetchone()
    if llm_ts_row and str(llm_ts_row["v"]).isdigit():
        age = int(time.time()) - int(llm_ts_row["v"])
        if age > 7200:
            llm_ring = "orange"
    else:
        llm_ring = "orange"

    engine_ring = "green" if engine_live and ws_live else ("orange" if engine_live else "red")
    if is_halted(db):
        engine_ring = "red"

    return {
        "ts": int(time.time()),
        "kite_latency_ms": kite_ms,
        "kite_ok": check_token(live=True),
        "kite_status_ring": kite_ring,
        "llm_status_ring": llm_ring,
        "engine_status_ring": engine_ring,
        "high_slippage_risk": high_slippage_risk,
        "latency_warn_ms": latency_warn,
        "db_ok": check_db(),
        "gcs_bucket": os.getenv("GCS_BUCKET", ""),
        "cpu_pct": load.get("cpu_pct"),
        "ram_pct": load.get("ram_pct"),
        "disk_pct": load.get("disk_pct"),
        "max_drawdown_pct": _max_drawdown_today(db),
        "halted": halt["halted"],
        "halt_reason": halt.get("reason"),
        "slumber": slumber,
        "circuit_breaker": halt["halted"] or slumber["active"],
    }

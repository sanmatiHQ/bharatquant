"""
Market-activity supervisor — keeps engine + dashboard running 24×7 in learn mode.

Lifecycle (ENGINE_24X7 / PAPER_ALWAYS_ON):
  ACTIVE always — ingest, RL, strategy discovery, heartbeat; trades only in session window.

Legacy (live + ENGINE_24X7=false):
  DORMANT → ARMING → ACTIVE → COOLING → DORMANT

Run: python3.11 -m src.ops.market_supervisor
GCP: systemd bharatquant-supervisor.service (always on)
macOS: scripts/install_launch_agent.sh
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from ..db.database import DB, DBConfig
from ..feeds.session_watcher import fetch_nse_status

load_dotenv()
logger = logging.getLogger("bharatquant.supervisor")
_TZ = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
RESTART_FLAG = Path(os.getenv("LOGS_DIR", "logs")) / "engine_restart.flag"
PID_FILE = Path(os.getenv("ENGINE_PID_FILE", "logs/engine.pid"))
DASH_PID_FILE = Path(os.getenv("DASH_PID_FILE", "logs/dashboard.pid"))


def _consume_restart_flag() -> bool:
    if not RESTART_FLAG.exists():
        return False
    RESTART_FLAG.unlink(missing_ok=True)
    return True


def _now_ist() -> datetime:
    return datetime.now(_TZ)


def _is_weekday() -> bool:
    return _now_ist().weekday() < 5


def _recent_gift_activity(db: DB, max_age_sec: int = 7200) -> bool:
    row = db._conn.execute(
        """
        SELECT ts FROM ingest_log WHERE event_type='GIFT_TICK'
        ORDER BY ts DESC LIMIT 1
        """
    ).fetchone()
    if not row:
        return False
    return int(time.time()) - int(row["ts"]) < max_age_sec


def _recent_fii_activity(db: DB, max_age_sec: int = 86400) -> bool:
    row = db._conn.execute(
        """
        SELECT ts FROM ingest_log WHERE event_type='FII_DII_UPDATE'
        ORDER BY ts DESC LIMIT 1
        """
    ).fetchone()
    if not row:
        return False
    return int(time.time()) - int(row["ts"]) < max_age_sec


def is_24x7_enabled() -> bool:
    """Never stop engine/dashboard — observe and learn around the clock."""
    if os.getenv("ENGINE_24X7", "true").lower() in ("1", "true", "yes"):
        return True
    if os.getenv("PAPER_ALWAYS_ON", "true").lower() in ("1", "true", "yes"):
        if os.getenv("TRADING_MODE", "paper") == "paper":
            return True
    return False


def evaluate_market_activity(db: DB, nse_status: str) -> tuple[bool, str]:
    """
    Return (should_run_engine, reason).
    Event-driven arming — not a fixed 9:20 cron.
    """
    if is_24x7_enabled():
        return True, "24x7_learn"

    now = _now_ist()
    hour = now.hour + now.minute / 60.0

    if nse_status in ("Pre-Open", "Open"):
        return True, f"nse_{nse_status.lower()}"

    if _is_weekday() and 8.0 <= hour <= 16.0:
        if _recent_gift_activity(db):
            return True, "gift_tick_recent"
        if _recent_fii_activity(db):
            return True, "fii_update_today"
        if 9.0 <= hour <= 15.75:
            return True, "weekday_session_window"

    if nse_status == "Close" and hour >= 16.0:
        return False, "nse_closed_post_market"

    if not _is_weekday():
        return False, "weekend"

    return False, "dormant"


def _pid_running(pid_file: Path, expect_module: str = "") -> bool:
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        return False
    try:
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "stat=,command="],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if not out:
            pid_file.unlink(missing_ok=True)
            return False
        stat, _, cmd = out.partition(" ")
        if stat.startswith("Z"):
            pid_file.unlink(missing_ok=True)
            return False
        if expect_module and expect_module not in cmd:
            pid_file.unlink(missing_ok=True)
            return False
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pid_file.unlink(missing_ok=True)
        return False


def _engine_stale(db: DB, max_age_sec: int | None = None) -> bool:
    if max_age_sec is None:
        max_age_sec = int(os.getenv("ENGINE_HEARTBEAT_MAX_SEC", "90"))
    row = db._conn.execute("SELECT v FROM settings WHERE k='engine_heartbeat_ts'").fetchone()
    if not row or not str(row["v"]).isdigit():
        return True
    return int(time.time()) - int(row["v"]) > max_age_sec


def _ensure_engine_running(db: DB) -> None:
    """Restart engine if PID is zombie, wrong process, or heartbeat stale."""
    running = _pid_running(PID_FILE, "src.engine.main")
    if running and not _engine_stale(db):
        return
    if running:
        logger.warning("engine_stale_or_zombie", extra={"action": "restart"})
        _stop_process(PID_FILE)
    _start_process("src.engine.main", PID_FILE)


def _ensure_dashboard_running() -> None:
    """Dashboard must stay up 24×7 — supervisor restarts it if crashed."""
    if not _pid_running(DASH_PID_FILE, "src.api.dashboard"):
        logger.warning("dashboard_down", extra={"action": "restart"})
        _start_process("src.api.dashboard", DASH_PID_FILE)


def _start_process(module: str, pid_file: Path) -> None:
    if _pid_running(pid_file):
        return
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    log_dir = Path(os.getenv("LOGS_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"{module.replace('.', '_')}.log"
    proc = subprocess.Popen(
        [sys.executable, "-m", module],
        cwd=str(root),
        stdout=open(log, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        env={**os.environ},
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    logger.info("process_started", extra={"py_module": module, "pid": proc.pid})


def _stop_process(pid_file: Path) -> None:
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        logger.info("process_stopped", extra={"pid": pid})
    except (OSError, ValueError):
        pass
    pid_file.unlink(missing_ok=True)


def start_engine_stack() -> None:
    if os.getenv("SUPERVISOR_USE_SYSTEMD", "").lower() in ("1", "true", "yes"):
        subprocess.run(["sudo", "systemctl", "start", "bharatquant-engine"], check=False)
        subprocess.run(["sudo", "systemctl", "start", "bharatquant-dashboard"], check=False)
        return
    _start_process("src.engine.main", PID_FILE)
    if not _pid_running(DASH_PID_FILE, "src.api.dashboard"):
        _start_process("src.api.dashboard", DASH_PID_FILE)


def stop_engine_stack() -> None:
    if is_24x7_enabled():
        logger.info("stop_skipped_24x7", extra={"mode": "learn_only"})
        return
    if os.getenv("SUPERVISOR_USE_SYSTEMD", "").lower() in ("1", "true", "yes"):
        subprocess.run(["sudo", "systemctl", "stop", "bharatquant-engine"], check=False)
        return
    _stop_process(PID_FILE)


def _persist_state(db: DB, state: str, reason: str) -> None:
    with db.tx() as conn:
        for k, v in [
            ("supervisor_state", state),
            ("supervisor_reason", reason),
            ("supervisor_ts", str(int(time.time()))),
        ]:
            conn.execute(
                "INSERT INTO settings(k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (k, v),
            )


async def run_supervisor() -> None:
    from ..ingest.gift_nifty import poll_gift_proxy
    from ..ingest.fii_dii import poll_fii_dii
    from ..events.bus import EventBus
    from ..events.types import MarketEvent

    logging.basicConfig(level=logging.INFO)
    db = DB(DBConfig(sqlite_path=os.getenv("SQLITE_PATH", "data/trading.db")))
    bus = EventBus()
    interval = float(os.getenv("SUPERVISOR_POLL_SEC", "30"))

    # Lightweight ingest for arming signals (supervisor only — not trading engine)
    async def noop_publish(ev: MarketEvent) -> None:
        await bus.publish(ev)

    asyncio.create_task(poll_gift_proxy(noop_publish, interval_sec=120.0, db=db))
    asyncio.create_task(poll_fii_dii(noop_publish, interval_sec=300.0, db=db))

    running = _pid_running(PID_FILE)
    logger.info(
        "supervisor_started",
        extra={"engine_running": running, "24x7": is_24x7_enabled()},
    )
    if is_24x7_enabled():
        start_engine_stack()

    while True:
        try:
            nse = await fetch_nse_status()
        except Exception:
            nse = "Unknown"
        should_run, reason = evaluate_market_activity(db, nse)
        is_running = _pid_running(PID_FILE, "src.engine.main")

        # Proactive token refresh (07:35 IST or when expired) — needs KITE_TOTP_SECRET
        from ..ops.healthchecks import check_token
        from ..ops.token_refresh import refresh_token_if_needed

        if should_run:
            await refresh_token_if_needed()

        if should_run and not is_running:
            start_engine_stack()
            _ensure_dashboard_running()
            _persist_state(db, "ACTIVE", reason)
            logger.info("engine_armed", extra={"reason": reason, "nse": nse})
        elif should_run and is_running:
            if _consume_restart_flag():
                logger.info("engine_restart_flag", extra={"action": "restart"})
                _stop_process(PID_FILE)
                _start_process("src.engine.main", PID_FILE)
            else:
                _ensure_engine_running(db)
            _ensure_dashboard_running()
            _persist_state(db, "ACTIVE", reason)
        elif not should_run and is_running:
            stop_engine_stack()
            _persist_state(db, "DORMANT", reason)
            logger.info("engine_dormant", extra={"reason": reason, "nse": nse})
        else:
            state = "ACTIVE" if is_running else "DORMANT"
            _persist_state(db, state, reason)

        if is_24x7_enabled():
            _ensure_dashboard_running()
            if not _pid_running(PID_FILE, "src.engine.main"):
                start_engine_stack()
                _persist_state(db, "ACTIVE", "24x7_recover")

        await asyncio.sleep(interval)


def main() -> None:
    asyncio.run(run_supervisor())


if __name__ == "__main__":
    main()

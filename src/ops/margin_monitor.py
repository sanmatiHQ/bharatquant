"""Continuous margin monitoring — halt if utilisation too high."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from ..alerts.webhook import send_telegram
from ..db.database import DB
from ..ops.kill_switch import set_halt

logger = logging.getLogger("bharatquant.margin_monitor")


def _load_kite():
    from kiteconnect import KiteConnect
    from ..feeds.kite_ticker import load_access_token

    api_key, token = load_access_token()
    k = KiteConnect(api_key=api_key)
    k.set_access_token(token)
    return k


def snapshot_margin(db: DB) -> dict:
    util_limit = float(os.getenv("MARGIN_UTIL_HALT_PCT", "85"))
    out = {"available": 0.0, "utilised": 0.0, "util_pct": 0.0, "halted": False}
    if os.getenv("TRADING_MODE", "paper") != "live":
        cash = float(db._conn.execute("SELECT IFNULL(SUM(delta),0) FROM cash_ledger").fetchone()[0])
        deployed = float(
            db._conn.execute(
                "SELECT IFNULL(SUM(qty*last_price),0) FROM positions WHERE qty > 0"
            ).fetchone()[0]
        )
        total = cash + deployed
        out["available"] = cash
        out["utilised"] = deployed
        out["util_pct"] = (deployed / total * 100.0) if total > 0 else 0.0
    else:
        try:
            kite = _load_kite()
            eq = kite.margins("equity")
            out["available"] = float(eq.get("available", {}).get("cash", 0) or 0)
            out["utilised"] = float(eq.get("utilised", {}).get("debits", 0) or 0)
            net = out["available"] + out["utilised"]
            out["util_pct"] = (out["utilised"] / net * 100.0) if net > 0 else 0.0
        except Exception:
            logger.exception("margin_snapshot_failed")
            return out

    ts = int(time.time())
    with db.tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO margin_snapshots(ts, available, utilised, util_pct) VALUES (?,?,?,?)",
            (ts, out["available"], out["utilised"], out["util_pct"]),
        )

    if out["util_pct"] >= util_limit:
        set_halt(db, reason=f"margin_util_{out['util_pct']:.0f}pct")
        out["halted"] = True
        logger.warning("margin_halt", extra=out)

    return out


async def run_margin_monitor_loop(db: DB, interval_sec: float | None = None) -> None:
    sec = interval_sec or float(os.getenv("MARGIN_MONITOR_SEC", "60"))
    while True:
        try:
            out = snapshot_margin(db)
            if out.get("halted"):
                await send_telegram(f"HALT margin util {out['util_pct']:.0f}%")
        except Exception:
            logger.exception("margin_monitor_error")
        await asyncio.sleep(sec)

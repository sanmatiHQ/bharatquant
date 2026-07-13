"""Broker ↔ internal DB reconciliation with alerts and repair."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from ..alerts.webhook import send_telegram
from ..db.database import DB

logger = logging.getLogger("bharatquant.reconcile")


def _load_kite():
    from kiteconnect import KiteConnect
    from ..feeds.kite_ticker import load_access_token

    api_key, token = load_access_token()
    k = KiteConnect(api_key=api_key)
    k.set_access_token(token)
    return k


def reconcile_positions(db: DB) -> dict[str, Any]:
    """Compare kite net positions vs internal positions table."""
    if os.getenv("TRADING_MODE", "paper") != "live":
        return _reconcile_paper_holdings(db)

    try:
        kite = _load_kite()
        net = kite.positions().get("net", [])
    except Exception as exc:
        logger.warning("reconcile_kite_unavailable", extra={"err": str(exc)})
        return {"ok": False, "error": str(exc), "mismatches": 0}

    broker: dict[str, dict] = {}
    for p in net:
        qty = int(p.get("quantity", 0) or 0)
        if qty == 0:
            continue
        sym = str(p.get("tradingsymbol", ""))
        broker[sym] = {
            "qty": qty,
            "avg": float(p.get("average_price", 0) or 0),
            "product": str(p.get("product", "CNC")),
        }

    internal_rows = db._conn.execute(
        "SELECT symbol, qty, avg_price, rail FROM positions WHERE qty > 0"
    ).fetchall()
    internal = {r["symbol"]: dict(r) for r in internal_rows}

    mismatches: list[dict] = []
    for sym, b in broker.items():
        i = internal.get(sym)
        if not i or int(i["qty"]) != b["qty"]:
            mismatches.append({"symbol": sym, "broker_qty": b["qty"], "internal_qty": int(i["qty"]) if i else 0})

    for sym, i in internal.items():
        if sym not in broker:
            mismatches.append({"symbol": sym, "broker_qty": 0, "internal_qty": int(i["qty"])})

    repaired = 0
    auto_repair = os.getenv("RECONCILE_AUTO_REPAIR", "true").lower() in ("1", "true", "yes")
    if auto_repair and mismatches:
        for m in mismatches:
            sym = m["symbol"]
            bq = m["broker_qty"]
            if bq > 0 and sym in broker:
                b = broker[sym]
                with db.tx() as conn:
                    conn.execute(
                        """
                        INSERT INTO positions(symbol, qty, avg_price, last_price, open_ts, rail)
                        VALUES (?,?,?,?,?,?)
                        ON CONFLICT(symbol) DO UPDATE SET
                          qty=excluded.qty, avg_price=excluded.avg_price, last_price=excluded.last_price
                        """,
                        (sym, bq, b["avg"], b["avg"], int(time.time()), b["product"]),
                    )
                repaired += 1
            elif bq == 0:
                with db.tx() as conn:
                    conn.execute("DELETE FROM positions WHERE symbol=?", (sym,))
                repaired += 1

    ts = int(time.time())
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO reconcile_log(ts, mismatches, details, repaired) VALUES (?,?,?,?)",
            (ts, len(mismatches), json.dumps(mismatches[:20]), repaired),
        )

    if mismatches:
        logger.warning("reconcile_mismatch", extra={"count": len(mismatches), "repaired": repaired})

    return {"ok": True, "mismatches": len(mismatches), "repaired": repaired, "details": mismatches, "alert": len(mismatches) > 0}


def _reconcile_paper_holdings(db: DB) -> dict[str, Any]:
    """Paper mode: cross-check kite_holdings vs positions for CNC awareness."""
    held = db._conn.execute("SELECT symbol, qty FROM kite_holdings WHERE qty > 0").fetchall()
    internal = db._conn.execute("SELECT symbol, qty FROM positions WHERE qty > 0").fetchall()
    broker_set = {r["symbol"]: int(r["qty"]) for r in held}
    internal_set = {r["symbol"]: int(r["qty"]) for r in internal}
    mismatches = []
    for sym, bq in broker_set.items():
        iq = internal_set.get(sym, 0)
        if bq != iq:
            mismatches.append({"symbol": sym, "kite_holdings_qty": bq, "internal_qty": iq})
    return {"ok": True, "mismatches": len(mismatches), "details": mismatches, "mode": "paper"}


async def run_reconciliation_loop(db: DB, interval_sec: float | None = None) -> None:
    sec = interval_sec or float(os.getenv("RECONCILE_INTERVAL_SEC", "300"))
    while True:
        try:
            result = reconcile_positions(db)
            if result.get("alert"):
                from ..alerts.webhook import send_telegram

                await send_telegram(
                    f"RECONCILE {result['mismatches']} mismatch(es) repaired={result.get('repaired', 0)}"
                )
        except Exception:
            logger.exception("reconcile_loop_error")
        await asyncio.sleep(sec)


async def startup_position_audit(db: DB) -> dict[str, Any]:
    """Run full reconcile on engine start before trading resumes."""
    result = reconcile_positions(db)
    logger.info("startup_position_audit", extra=result)
    return result

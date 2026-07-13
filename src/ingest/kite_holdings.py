"""Sync real Zerodha holdings — read-only, agent uses to avoid duplicate exposure."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Optional

from ..db.database import DB

logger = logging.getLogger("bharatquant.kite_holdings")


def _kite_client():
    from kiteconnect import KiteConnect

    from ..feeds.kite_ticker import load_access_token

    try:
        api_key, token = load_access_token()
    except Exception:
        return None
    if not api_key or not token:
        return None
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(token)
    return kite


def fetch_holdings() -> list[dict[str, Any]]:
    kite = _kite_client()
    if not kite:
        return []
    out: list[dict[str, Any]] = []
    try:
        for h in kite.holdings() or []:
            sym = str(h.get("tradingsymbol", ""))
            if not sym:
                continue
            qty = int(h.get("quantity", 0) or 0)
            if qty <= 0:
                continue
            out.append({
                "symbol": sym,
                "qty": qty,
                "avg_price": float(h.get("average_price", 0) or 0),
                "ltp": float(h.get("last_price", 0) or 0),
                "pnl": float(h.get("pnl", 0) or 0),
                "product": str(h.get("product", "CNC")),
                "exchange": str(h.get("exchange", "NSE")),
            })
    except Exception:
        logger.exception("kite_holdings_fetch_failed")
    return out


def fetch_positions() -> list[dict[str, Any]]:
    kite = _kite_client()
    if not kite:
        return []
    out: list[dict[str, Any]] = []
    try:
        net = kite.positions() or {}
        for bucket in ("day", "net"):
            for p in net.get(bucket) or []:
                qty = int(p.get("quantity", 0) or 0)
                if qty == 0:
                    continue
                sym = str(p.get("tradingsymbol", ""))
                out.append({
                    "symbol": sym,
                    "qty": qty,
                    "avg_price": float(p.get("average_price", 0) or 0),
                    "ltp": float(p.get("last_price", 0) or 0),
                    "pnl": float(p.get("pnl", 0) or 0),
                    "product": str(p.get("product", "")),
                    "exchange": str(p.get("exchange", "NSE")),
                })
    except Exception:
        logger.exception("kite_positions_fetch_failed")
    return out


def sync_to_db(db: DB) -> int:
    ts = int(time.time())
    holdings = fetch_holdings()
    positions = fetch_positions()
    seen = set()
    with db.tx() as conn:
        conn.execute("DELETE FROM kite_holdings")
        for row in holdings + positions:
            sym = row["symbol"]
            if sym in seen:
                continue
            seen.add(sym)
            conn.execute(
                """
                INSERT INTO kite_holdings(symbol, qty, avg_price, ltp, pnl, product, exchange, synced_ts)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    sym,
                    row["qty"],
                    row["avg_price"],
                    row["ltp"],
                    row["pnl"],
                    row["product"],
                    row["exchange"],
                    ts,
                ),
            )
    logger.info("kite_holdings_synced", extra={"count": len(seen)})
    return len(seen)


def real_symbols_held(db: DB) -> set[str]:
    rows = db._conn.execute(
        "SELECT symbol FROM kite_holdings WHERE qty > 0"
    ).fetchall()
    return {str(r["symbol"]) for r in rows}


def real_holdings_value(db: DB) -> float:
    return float(
        db._conn.execute(
            "SELECT IFNULL(SUM(qty * ltp), 0) FROM kite_holdings WHERE qty > 0"
        ).fetchone()[0]
    )


async def poll_kite_holdings(db: DB, interval_sec: float = 900.0) -> None:
    import asyncio

    while True:
        try:
            sync_to_db(db)
        except Exception:
            logger.exception("kite_holdings_poll_error")
        await asyncio.sleep(interval_sec)

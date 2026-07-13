"""Store bid-ask spread from Kite MODE_FULL depth ticks."""
from __future__ import annotations

import logging
import time

from ..db.database import DB

logger = logging.getLogger("bharatquant.depth")


def orderbook_imbalance_from_depth(depth: dict, *, levels: int = 5) -> float:
    """OBI = (bid_vol - ask_vol) / (bid_vol + ask_vol) over top N depth levels."""
    buy = depth.get("buy") or []
    sell = depth.get("sell") or []
    bid_vol = sum(int(x.get("quantity", 0) or 0) for x in buy[:levels])
    ask_vol = sum(int(x.get("quantity", 0) or 0) for x in sell[:levels])
    total = bid_vol + ask_vol
    if total <= 0:
        return 0.0
    return (bid_vol - ask_vol) / total


def orderbook_imbalance_from_tick(raw: dict, *, levels: int = 5) -> float:
    depth = raw.get("depth") or {}
    return orderbook_imbalance_from_depth(depth, levels=levels)


def spread_from_tick(raw: dict) -> tuple[float, float, float]:
    """Returns (bid, ask, spread_bps) from Kite depth tick."""
    depth = raw.get("depth") or {}
    buy = depth.get("buy") or []
    sell = depth.get("sell") or []
    bid = float(buy[0]["price"]) if buy else float(raw.get("last_price", 0) or 0)
    ask = float(sell[0]["price"]) if sell else bid
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0
    spread_bps = ((ask - bid) / mid * 10000.0) if mid > 0 else 0.0
    return bid, ask, spread_bps


def record_depth(db: DB, symbol: str, raw: dict) -> tuple[float, float]:
    bid, ask, spread_bps = spread_from_tick(raw)
    depth = raw.get("depth") or {}
    buy = depth.get("buy") or []
    sell = depth.get("sell") or []
    bid_qty = int(buy[0].get("quantity", 0)) if buy else 0
    ask_qty = int(sell[0].get("quantity", 0)) if sell else 0
    obi = orderbook_imbalance_from_depth(depth)
    ts = int(time.time())
    with db.tx() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO depth_snapshots(symbol, ts, bid, ask, spread_bps, bid_qty, ask_qty, obi)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (symbol.replace("NSE:", ""), ts, bid, ask, spread_bps, bid_qty, ask_qty, obi),
        )
    return spread_bps, obi


def latest_spread_bps(db: DB, symbol: str) -> float:
    sym = symbol.replace("NSE:", "")
    row = db._conn.execute(
        "SELECT spread_bps FROM depth_snapshots WHERE symbol=? ORDER BY ts DESC LIMIT 1",
        (sym,),
    ).fetchone()
    return float(row["spread_bps"]) if row else 0.0


def latest_obi(db: DB, symbol: str) -> float:
    sym = symbol.replace("NSE:", "")
    row = db._conn.execute(
        "SELECT obi, bid_qty, ask_qty FROM depth_snapshots WHERE symbol=? ORDER BY ts DESC LIMIT 1",
        (sym,),
    ).fetchone()
    if not row:
        return 0.0
    if row["obi"] is not None:
        return float(row["obi"])
    bid_qty = int(row["bid_qty"] or 0)
    ask_qty = int(row["ask_qty"] or 0)
    total = bid_qty + ask_qty
    if total <= 0:
        return 0.0
    return (bid_qty - ask_qty) / total

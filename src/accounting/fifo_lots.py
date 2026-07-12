"""FIFO lot accounting + STCG/LTCG classification on sells."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Tuple

from ..costs.cost_engine import CostEngine
from ..db.database import DB
from ..data.sector_mapper import sector_for_symbol


@dataclass
class LotFill:
    qty: int
    buy_price: float
    buy_ts: int
    tax_class: str
    pnl: float


def open_lot(db: DB, symbol: str, qty: int, price: float, ts: int, rail: str = "CNC", trade_id: int | None = None) -> None:
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO fifo_lots(symbol, qty, remaining_qty, buy_price, buy_ts, rail, trade_id)
            VALUES (?,?,?,?,?,?,?)
            """,
            (symbol, qty, qty, price, ts, rail, trade_id),
        )
        row = conn.execute("SELECT qty, avg_price FROM positions WHERE symbol=?", (symbol,)).fetchone()
        if row:
            old_q, old_avg = int(row["qty"]), float(row["avg_price"])
            new_q = old_q + qty
            new_avg = (old_avg * old_q + price * qty) / new_q if new_q else price
            conn.execute(
                """
                UPDATE positions SET qty=?, avg_price=?, last_price=?, rail=?, open_ts=?
                WHERE symbol=?
                """,
                (new_q, new_avg, price, rail, ts, symbol),
            )
        else:
            sector = sector_for_symbol(symbol, db)
            conn.execute(
                """
                INSERT INTO positions(symbol, qty, avg_price, last_price, open_ts, rail, sector)
                VALUES (?,?,?,?,?,?,?)
                """,
                (symbol, qty, price, price, ts, rail, sector),
            )


def close_lots_fifo(
    db: DB,
    symbol: str,
    sell_qty: int,
    sell_price: float,
    sell_ts: int,
    costs: CostEngine | None = None,
) -> Tuple[List[LotFill], str]:
    """Consume lots FIFO; return fills + dominant tax class for trade row."""
    costs = costs or CostEngine(slippage_bps=0)
    fills: List[LotFill] = []
    remaining = sell_qty
    conn = db._conn
    cur = conn.execute(
        """
        SELECT id, remaining_qty, buy_price, buy_ts FROM fifo_lots
        WHERE symbol=? AND remaining_qty > 0 ORDER BY buy_ts ASC, id ASC
        """,
        (symbol,),
    )
    tax_counts: dict[str, int] = {}
    for lot in cur.fetchall():
        if remaining <= 0:
            break
        lot_id = int(lot["id"])
        avail = int(lot["remaining_qty"])
        take = min(avail, remaining)
        hold_days = max(0, (sell_ts - int(lot["buy_ts"])) // 86400)
        tax = costs.classify_tax(hold_days)
        pnl = (sell_price - float(lot["buy_price"])) * take
        fills.append(LotFill(take, float(lot["buy_price"]), int(lot["buy_ts"]), tax, pnl))
        tax_counts[tax] = tax_counts.get(tax, 0) + take
        new_rem = avail - take
        conn.execute("UPDATE fifo_lots SET remaining_qty=? WHERE id=?", (new_rem, lot_id))
        remaining -= take
    conn.commit()
    if remaining > 0:
        raise ValueError(f"Insufficient FIFO lots for {symbol}: short {remaining}")
    pos = conn.execute("SELECT qty FROM positions WHERE symbol=?", (symbol,)).fetchone()
    if pos:
        new_q = int(pos["qty"]) - sell_qty
        if new_q <= 0:
            conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        else:
            conn.execute("UPDATE positions SET qty=?, last_price=? WHERE symbol=?", (new_q, sell_price, symbol))
        conn.commit()
    dominant = max(tax_counts, key=tax_counts.get) if tax_counts else "NA"
    return fills, dominant


def load_positions_ctx(db: DB) -> dict:
    cur = db._conn.execute("SELECT symbol, qty, avg_price, last_price, rail FROM positions")
    out = {}
    for r in cur.fetchall():
        out[r["symbol"]] = {
            "qty": int(r["qty"]),
            "avg_price": float(r["avg_price"]),
            "last_price": float(r["last_price"]),
            "rail": r["rail"] or "CNC",
            "stop_loss_pct": 4.0,
        }
    return out

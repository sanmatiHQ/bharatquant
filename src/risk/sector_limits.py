"""Sector concentration limits."""
from __future__ import annotations

import os
from collections import Counter

from ..db.database import DB
from ..data.sector_mapper import sector_for_symbol

_DEFAULT_SECTOR = "OTHER"


def symbol_sector(db: DB, symbol: str) -> str:
    return sector_for_symbol(symbol, db)


def sector_exposure(db: DB) -> Counter:
    c: Counter = Counter()
    for r in db._conn.execute("SELECT symbol, qty, last_price, sector FROM positions"):
        sec = r["sector"] or _DEFAULT_SECTOR
        c[sec] += float(r["qty"]) * float(r["last_price"])
    return c


def can_add_sector(db: DB, symbol: str, rupees: float) -> tuple[bool, str]:
    max_pct = float(os.getenv("MAX_SECTOR_PCT", "40"))
    total = float(db._conn.execute("SELECT IFNULL(SUM(qty*last_price),0) h FROM positions").fetchone()["h"])
    cash = float(db._conn.execute("SELECT IFNULL(SUM(delta),0) c FROM cash_ledger").fetchone()["c"])
    equity = total + cash
    if equity <= 0:
        return True, "ok"
    sec = symbol_sector(db, symbol)
    exp = sector_exposure(db)
    new_sec_val = exp.get(sec, 0) + rupees
    if new_sec_val / equity * 100 > max_pct:
        return False, f"sector_cap_{sec}"
    return True, "ok"

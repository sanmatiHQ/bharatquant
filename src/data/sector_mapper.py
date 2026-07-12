"""Sector lookup for concentration limits."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from ..db.database import DB

logger = logging.getLogger("bharatquant.sector")

# Nifty sector ETF proxies for coarse mapping when no CSV
_SECTOR_ETF_HINTS = {
    "BANK": "BANK",
    "HDFC": "BANK",
    "ICICI": "BANK",
    "AXIS": "BANK",
    "INFY": "IT",
    "TCS": "IT",
    "WIPRO": "IT",
    "RELIANCE": "ENERGY",
    "ONGC": "ENERGY",
    "ITC": "FMCG",
    "HINDUNILVR": "FMCG",
}


def sector_for_symbol(symbol: str, db: DB | None = None) -> str:
    sym = symbol.replace("NSE:", "").upper()
    if db is not None:
        row = db._conn.execute("SELECT sector FROM symbol_sectors WHERE symbol=?", (sym,)).fetchone()
        if row and row["sector"]:
            return str(row["sector"])
    for hint, sec in _SECTOR_ETF_HINTS.items():
        if hint in sym:
            return sec
    return "OTHER"


def load_sector_map(db: DB, csv_path: str | Path) -> int:
    path = Path(csv_path)
    if not path.exists():
        logger.info("sector_map_missing", extra={"path": str(path)})
        return 0
    n = 0
    with db.tx() as conn:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = (row.get("symbol") or row.get("tradingsymbol", "")).replace("NSE:", "").strip()
                sec = (row.get("sector") or row.get("industry", "")).strip()
                if not sym or not sec:
                    continue
                conn.execute(
                    """
                    INSERT INTO symbol_sectors(symbol, sector) VALUES (?,?)
                    ON CONFLICT(symbol) DO UPDATE SET sector=excluded.sector
                    """,
                    (sym, sec),
                )
                n += 1
    return n

"""ASM/GSM and F&O ban symbol exclusion."""
from __future__ import annotations

import logging
import time
from typing import Set

import httpx

from ..db.database import DB

logger = logging.getLogger("bharatquant.asm_gsm")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


async def fetch_asm_gsm() -> list[dict]:
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        await client.get("https://www.nseindia.com", headers=NSE_HEADERS)
        r = await client.get("https://www.nseindia.com/api/regulatory-watchlist", headers=NSE_HEADERS)
        r.raise_for_status()
        data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


def sync_asm_gsm_db(db: DB, rows: list[dict]) -> int:
    ts = int(time.time())
    n = 0
    with db.tx() as conn:
        for row in rows:
            sym = str(row.get("symbol", row.get("sm_symbol", ""))).strip()
            stage = str(row.get("series", row.get("stage", "ASM"))).strip()
            if not sym:
                continue
            conn.execute(
                """
                INSERT INTO asm_gsm_symbols(symbol, stage, updated_ts) VALUES (?,?,?)
                ON CONFLICT(symbol) DO UPDATE SET stage=excluded.stage, updated_ts=excluded.updated_ts
                """,
                (sym, stage, ts),
            )
            n += 1
    return n


def is_excluded(db: DB, symbol: str) -> bool:
    sym = symbol.replace("NSE:", "")
    row = db._conn.execute("SELECT stage FROM asm_gsm_symbols WHERE symbol=?", (sym,)).fetchone()
    if not row:
        return False
    stage = str(row["stage"]).upper()
    return stage in ("GSM", "ASM", "STAGE1", "STAGE2", "STAGE3", "STAGE4")


def excluded_set(db: DB) -> Set[str]:
    cur = db._conn.execute("SELECT symbol FROM asm_gsm_symbols")
    return {r["symbol"] for r in cur.fetchall()}

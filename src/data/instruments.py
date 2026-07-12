"""Load and cache NSE instrument tokens from Kite — required for real OHLC."""
from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import httpx
import pandas as pd

from ..db.database import DB

KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments"


@dataclass
class InstrumentStore:
    db: DB

    def _upsert_rows(self, rows: list[tuple]) -> int:
        with self.db.tx() as conn:
            conn.executemany(
                """
                INSERT INTO instruments(tradingsymbol, instrument_token, exchange, updated_ts)
                VALUES (?,?,?,?)
                ON CONFLICT(tradingsymbol) DO UPDATE SET
                  instrument_token=excluded.instrument_token,
                  exchange=excluded.exchange,
                  updated_ts=excluded.updated_ts
                """,
                rows,
            )
        return len(rows)

    def cache_from_public_kite(self) -> int:
        """No auth — same CSV as universe_builder."""
        with httpx.Client(timeout=60.0) as client:
            r = client.get(KITE_INSTRUMENTS_URL)
            r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        nse_eq = df[(df.get("segment") == "NSE") & (df.get("instrument_type") == "EQ")]
        ts = int(time.time())
        rows = [
            (str(r["tradingsymbol"]), int(r["instrument_token"]), "NSE", ts)
            for _, r in nse_eq.iterrows()
        ]
        return self._upsert_rows(rows)

    def cache_from_universe_csv(self, csv_path: str) -> int:
        """Seed tokens from universe CSV (has instrument_token column)."""
        path = Path(csv_path)
        if not path.exists():
            return 0
        ts = int(time.time())
        rows = []
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = (row.get("tradingsymbol") or row.get("symbol") or "").replace("NSE:", "")
                tok = row.get("instrument_token")
                if sym and tok:
                    rows.append((sym, int(tok), "NSE", ts))
        if rows:
            return self._upsert_rows(rows)
        return 0

    def _cache_from_kite(self, feed) -> int:
        df = feed.fetch_instruments()
        nse_eq = df[(df.get("segment") == "NSE") & (df.get("instrument_type") == "EQ")]
        ts = int(time.time())
        rows = [
            (str(r["tradingsymbol"]), int(r["instrument_token"]), "NSE", ts)
            for _, r in nse_eq.iterrows()
        ]
        return self._upsert_rows(rows)

    def ensure_cache(self, feed=None, universe_csv: str | None = None, max_age_sec: int = 86400) -> None:
        cur = self.db._conn.execute("SELECT MAX(updated_ts) AS ts FROM instruments")
        row = cur.fetchone()
        last = int(row["ts"] or 0)
        stale = int(time.time()) - last > max_age_sec or last == 0

        if universe_csv:
            self.cache_from_universe_csv(universe_csv)

        if stale:
            if feed is not None:
                self._cache_from_kite(feed)
            else:
                self.cache_from_public_kite()

    def token_for(self, symbol: str) -> int:
        """Resolve NSE:RELIANCE or RELIANCE to instrument_token."""
        sym = symbol.upper().replace("NSE:", "").strip()
        cur = self.db._conn.execute(
            "SELECT instrument_token FROM instruments WHERE tradingsymbol = ?",
            (sym,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"No instrument_token for symbol={symbol!r}. Run instrument cache.")
        return int(row["instrument_token"])

    def load_universe(self, csv_path: str) -> List[str]:
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Universe CSV missing: {csv_path}")
        syms: List[str] = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw = row.get("symbol") or row.get("tradingsymbol") or ""
                if raw:
                    syms.append(raw.strip())
        if not syms:
            raise ValueError(f"Universe CSV empty: {csv_path}")
        return syms

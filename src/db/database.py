"""
SQLite database helper with idempotent migrations and typed CRUD helpers.
"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any, Iterable, Iterator, Sequence


@dataclass
class DBConfig:
    sqlite_path: str


class DB:
    def __init__(self, cfg: DBConfig) -> None:
        self.path = Path(cfg.sqlite_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._bootstrap()

    def _bootstrap(self) -> None:
        migrations_path = Path(__file__).with_name("migrations.sql")
        with open(migrations_path, "r", encoding="utf-8") as f:
            sql = f.read()
        cur = self._conn.cursor()
        cur.executescript(sql)
        self._conn.commit()
        self._apply_patches()

    def _apply_patches(self) -> None:
        """Idempotent column adds for existing SQLite files."""
        patches = [
            "ALTER TABLE strategy_ledger ADD COLUMN delivery_id TEXT",
            "ALTER TABLE positions ADD COLUMN rail TEXT DEFAULT 'CNC'",
            "ALTER TABLE positions ADD COLUMN sector TEXT DEFAULT ''",
            "ALTER TABLE trades ADD COLUMN order_id TEXT",
        ]
        for stmt in patches:
            try:
                self._conn.execute(stmt)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:  # noqa: BLE001
            self._conn.rollback()
            raise

    # CRUD helpers
    def add_cash(self, ts: int, delta: float, note: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO cash_ledger(ts, delta, note) VALUES (?, ?, ?)",
                (ts, delta, note),
            )

    def record_trade(
        self,
        ts: int,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        amount: float,
        reason: str,
        fees: float,
        stcg_ltcg: str,
        order_id: str | None = None,
    ) -> int:
        with self.tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO trades(ts, symbol, side, qty, price, amount, reason, fees, stcg_ltcg, order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, symbol, side, qty, price, amount, reason, fees, stcg_ltcg, order_id),
            )
            return int(cur.lastrowid)

    def upsert_position(self, symbol: str, qty: int, avg_price: float, last_price: float, open_ts: int) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                INSERT INTO positions(symbol, qty, avg_price, last_price, open_ts)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                  qty=excluded.qty,
                  avg_price=excluded.avg_price,
                  last_price=excluded.last_price
                """,
                (symbol, qty, avg_price, last_price, open_ts),
            )

    def record_screen(
        self,
        run_ts: int,
        rows: Sequence[tuple[int, str, float, float | None, float | None, float | None, int | None]],
    ) -> None:
        with self.tx() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO screening_results(run_ts, symbol, momentum_score, r1m, r3m, rsi, ma_align)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def snapshot_portfolio(
        self,
        ts: int,
        cash: float,
        holdings_value: float,
        total_value: float,
        realized_pnl: float,
        unrealized_pnl: float,
        max_drawdown: float,
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO portfolio_history(ts, cash, holdings_value, total_value, realized_pnl, unrealized_pnl, max_drawdown)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, cash, holdings_value, total_value, realized_pnl, unrealized_pnl, max_drawdown),
            )



def main() -> None:
    from .database import DB, DBConfig  # type: ignore
    sqlite_path = os.getenv('SQLITE_PATH', 'data/trading.db')
    DB(DBConfig(sqlite_path=sqlite_path))
    print(f'Initialized DB at {sqlite_path}')


if __name__ == '__main__':
    main()

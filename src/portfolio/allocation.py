"""
Daily portfolio allocation — runs after pre-open screen.

Portfolio sizing = how much money goes into each stock today, not equal slices.
Volatile names get smaller weight; calmer names get more (inverse-vol / equal-risk).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from ..data.instruments import InstrumentStore
from ..data.kite_data_feed import KiteDataFeed
from ..db.database import DB
from ..portfolio.sizing import inverse_vol_weights, rupee_qty_map
from ..screening.momentum_screener import DataUnavailableError

logger = logging.getLogger("bharatquant.allocation")


def _daily_budget() -> float:
    lo = float(os.getenv("DAILY_INVESTMENT_MIN", "500"))
    hi = float(os.getenv("DAILY_INVESTMENT_MAX", "1000"))
    return min(hi, max(lo, float(os.getenv("DAILY_INVESTMENT", hi))))


def build_close_panel(
    symbols: List[str],
    feed: KiteDataFeed,
    instruments: InstrumentStore,
    *,
    lookback_days: int = 90,
) -> pd.DataFrame:
    """Fetch Kite daily closes for inverse-vol — real OHLC only."""
    end = datetime.utcnow().date()
    start = end - timedelta(days=lookback_days)
    series: Dict[str, pd.Series] = {}
    for sym in symbols:
        full = sym if sym.startswith("NSE:") else f"NSE:{sym}"
        try:
            token = instruments.token_for(full)
            df = feed.historical(
                instrument_token=token,
                start=start.isoformat(),
                end=end.isoformat(),
                interval="day",
            )
            if df is None or df.empty or len(df) < 21:
                continue
            s = df.set_index("date")["close"].astype(float)
            s.name = sym.replace("NSE:", "")
            series[s.name] = s
        except (KeyError, DataUnavailableError, Exception) as exc:
            logger.warning("allocation_hist_skip", extra={"symbol": sym, "error": str(exc)})
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).dropna(how="all").ffill().dropna(how="any")


def compute_allocation(
    screen_df: pd.DataFrame,
    close_panel: pd.DataFrame,
    *,
    max_positions: int,
    daily_budget: float,
    max_rupees_per_trade: float,
) -> pd.DataFrame:
    """
    Turn screen hits + Kite close history into per-symbol qty targets.
    """
    if screen_df.empty:
        return pd.DataFrame()

    candidates = screen_df.head(max(max_positions * 3, 10))["symbol"].tolist()
    panel_cols = [c for c in candidates if c in close_panel.columns]
    if len(panel_cols) < 1:
        # Fallback: equal weight on top scores using last_close from screen
        top = screen_df.head(max_positions)
        w = 1.0 / len(top)
        rows = []
        for r in top.itertuples(index=False):
            px = float(r.last_close)
            budget = daily_budget * w
            qty = max(1, int(min(max_rupees_per_trade, budget) // px))
            rows.append(
                {
                    "symbol": r.symbol,
                    "weight": w,
                    "target_qty": qty,
                    "target_rupees": qty * px,
                    "last_price": px,
                }
            )
        return pd.DataFrame(rows)

    sub = close_panel[panel_cols]
    weights = inverse_vol_weights(sub, max_names=max_positions)
    if not weights:
        return pd.DataFrame()

    prices = {}
    for sym in weights:
        if sym in screen_df["symbol"].values:
            prices[sym] = float(screen_df.loc[screen_df["symbol"] == sym, "last_close"].iloc[0])
        else:
            prices[sym] = float(sub[sym].iloc[-1])

    qty_map = rupee_qty_map(weights, prices, daily_budget)
    rows = []
    for sym, w in weights.items():
        px = prices.get(sym, 0.0)
        if px <= 0 or sym not in qty_map:
            continue
        qty = qty_map[sym]
        cap_qty = max(1, int(max_rupees_per_trade // px))
        qty = min(qty, cap_qty)
        rows.append(
            {
                "symbol": sym,
                "weight": w,
                "target_qty": qty,
                "target_rupees": qty * px,
                "last_price": px,
            }
        )
    return pd.DataFrame(rows)


def persist_allocation(db: DB, alloc_df: pd.DataFrame, run_ts: Optional[int] = None) -> int:
    ts = run_ts or int(time.time())
    if alloc_df.empty:
        return ts
    with db.tx() as conn:
        conn.execute("DELETE FROM portfolio_allocation WHERE run_ts < ?", (ts - 86400 * 7,))
        for r in alloc_df.itertuples(index=False):
            conn.execute(
                """
                INSERT OR REPLACE INTO portfolio_allocation
                (run_ts, symbol, weight, target_qty, target_rupees, last_price)
                VALUES (?,?,?,?,?,?)
                """,
                (ts, r.symbol, float(r.weight), int(r.target_qty), float(r.target_rupees), float(r.last_price)),
            )
    logger.info(
        "allocation_persisted",
        extra={"run_ts": ts, "names": len(alloc_df), "budget": _daily_budget()},
    )
    return ts


def build_from_screen(
    db: DB,
    screen_df: pd.DataFrame,
    feed: Optional[KiteDataFeed] = None,
    instruments: Optional[InstrumentStore] = None,
) -> pd.DataFrame:
    max_pos = int(os.getenv("MAX_POSITIONS", "5"))
    max_trade = float(os.getenv("MAX_RUPEES_PER_TRADE", "1000"))
    budget = _daily_budget()

    if screen_df.empty:
        return pd.DataFrame()

    feed = feed or KiteDataFeed()
    instruments = instruments or InstrumentStore(db=db)
    instruments.ensure_cache(feed=feed if hasattr(feed, "fetch_instruments") else None)

    top_syms = screen_df.head(max(max_pos * 3, 10))["symbol"].tolist()
    panel = build_close_panel(top_syms, feed, instruments)
    alloc = compute_allocation(
        screen_df,
        panel,
        max_positions=max_pos,
        daily_budget=budget,
        max_rupees_per_trade=max_trade,
    )
    persist_allocation(db, alloc)
    return alloc


def load_target_qty(db: DB, symbol: str) -> Optional[int]:
    sym = symbol.replace("NSE:", "")
    row = db._conn.execute(
        """
        SELECT target_qty FROM portfolio_allocation
        WHERE run_ts = (SELECT MAX(run_ts) FROM portfolio_allocation)
          AND symbol = ?
        """,
        (sym,),
    ).fetchone()
    return int(row["target_qty"]) if row else None


def is_allocated_symbol(db: DB, symbol: str) -> bool:
    return load_target_qty(db, symbol) is not None


def bootstrap_watchlist_allocation(db: DB, symbols: list[str]) -> int:
    """Seed equal-weight targets so BUYs are not blocked before pre-open screen."""
    row = db._conn.execute("SELECT MAX(run_ts) AS ts FROM portfolio_allocation").fetchone()
    if row and row["ts"] and int(time.time()) - int(row["ts"]) < 3600:
        return int(row["ts"])
    if not symbols:
        return 0
    max_pos = int(os.getenv("MAX_POSITIONS", "8"))
    max_trade = float(os.getenv("MAX_RUPEES_PER_TRADE", "1000"))
    budget = _daily_budget()
    picks = symbols[: max(max_pos * 2, 10)]
    w = 1.0 / len(picks)
    rows = []
    for sym in picks:
        sym_clean = sym.replace("NSE:", "")
        px = 500.0
        px_row = db._conn.execute(
            "SELECT last_price FROM portfolio_allocation WHERE symbol=? ORDER BY run_ts DESC LIMIT 1",
            (sym_clean,),
        ).fetchone()
        if px_row and px_row["last_price"]:
            px = float(px_row["last_price"])
        qty = max(1, int(min(max_trade, budget * w) // px))
        rows.append(
            {
                "symbol": sym_clean,
                "weight": w,
                "target_qty": qty,
                "target_rupees": qty * px,
                "last_price": px,
            }
        )
    import pandas as pd

    return persist_allocation(db, pd.DataFrame(rows))

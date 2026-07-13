"""
Momentum screener — real Kite OHLC only. Fails loud if token or history missing.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd

from ..db.database import DB
from ..data.kite_data_feed import KiteDataFeed
from ..data.instruments import InstrumentStore
from ..features.feature_store import FeatureStore
from ..utils.logging_setup import get_logger


class DataUnavailableError(RuntimeError):
    """Raised when live market data cannot be loaded — never use dummy OHLC."""


@dataclass
class ScreenerConfig:
    universe_csv: str
    min_score: float
    logs_dir: str
    lookback_days: int = 400


class MomentumScreener:
    def __init__(
        self,
        cfg: ScreenerConfig,
        db: DB,
        feed: Optional[KiteDataFeed] = None,
    ) -> None:
        self.cfg = cfg
        self.db = db
        self.logger = get_logger("screening", logs_dir=cfg.logs_dir)
        self.feed = feed or KiteDataFeed()
        self.instruments = InstrumentStore(db=db)
        self.fs = FeatureStore()

    def _score(self, feats: dict) -> float:
        return float(
            0.4 * feats.get("r3m", 0)
            + 0.4 * feats.get("r1m", 0)
            + 0.1 * (feats.get("rsi", 50) / 100.0)
            + 0.1 * feats.get("ma_align", 0)
        )

    def _historical(self, token: int, symbol: str) -> pd.DataFrame:
        end = datetime.utcnow().date()
        start = end - timedelta(days=self.cfg.lookback_days)
        df = self.feed.historical(
            instrument_token=token,
            start=start.isoformat(),
            end=end.isoformat(),
            interval="day",
        )
        if df is None or df.empty or len(df) < int(os.getenv("SCREEN_MIN_HISTORY_ROWS", "90")):
            raise DataUnavailableError(
                f"Insufficient OHLC for {symbol}: got {0 if df is None else len(df)} rows"
            )
        return df

    def _screen_symbol(self, sym: str) -> tuple[Optional[dict], bool]:
        """Returns (row dict or None, is_error)."""
        try:
            token = self.instruments.token_for(sym)
            hist = self._historical(token, sym)
            feats = self.fs.compute_features(hist)
            score = self._score(feats)
            if score < self.cfg.min_score:
                return None, False
            clean = sym.replace("NSE:", "")
            return (
                {
                    "symbol": clean,
                    "score": score,
                    "r1m": feats["r1m"],
                    "r3m": feats["r3m"],
                    "rsi": feats["rsi"],
                    "ma_align": feats["ma_align"],
                    "last_close": float(hist["close"].iloc[-1]),
                },
                False,
            )
        except (KeyError, DataUnavailableError) as exc:
            self.logger.warning("screen_skip", extra={"symbol": sym, "error": str(exc)})
            return None, True

    def run(self) -> pd.DataFrame:
        self.instruments.ensure_cache(
            feed=self.feed if hasattr(self.feed, "fetch_instruments") else None,
            universe_csv=self.cfg.universe_csv,
        )
        syms = self.instruments.load_universe(self.cfg.universe_csv)
        workers = int(os.getenv("SCREEN_PARALLEL_WORKERS", "10"))
        self.logger.info("screen_start", extra={"universe_size": len(syms), "workers": workers})
        rows: list[dict] = []
        errors = 0
        done = 0
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._screen_symbol, sym): sym for sym in syms}
            for fut in as_completed(futures):
                done += 1
                if done % 100 == 0:
                    self.logger.info(
                        "screen_progress",
                        extra={"done": done, "total": len(syms), "hits": len(rows)},
                    )
                row, is_err = fut.result()
                with lock:
                    if row:
                        rows.append(row)
                    if is_err:
                        errors += 1

        if not rows and errors == len(syms):
            raise DataUnavailableError(
                f"Screening failed for entire universe ({len(syms)} symbols). Check Kite token."
            )

        df = pd.DataFrame(rows)
        if df.empty:
            self.logger.info("screen_run", extra={"n": 0, "errors": errors})
            return df

        df = df.sort_values("score", ascending=False).reset_index(drop=True)
        run_ts = int(time.time())
        to_store = [
            (run_ts, r.symbol, float(r.score), float(r.r1m), float(r.r3m), float(r.rsi), int(r.ma_align))
            for r in df.itertuples(index=False)
        ]
        self.db.record_screen(run_ts, to_store)
        self.logger.info("screen_run", extra={"n": len(df), "errors": errors})
        return df

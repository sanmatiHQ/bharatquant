"""NSE index OHLC for dashboard — Kite (live) → NSE spot → Yahoo fallback."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .market_feed_client import fetch_nse_all_indices, fetch_nse_market_status

logger = logging.getLogger("bharatquant.index_data")
_IST = ZoneInfo("Asia/Kolkata")

INDEX_MAP: dict[str, dict[str, str]] = {
    "nifty50": {
        "nse_name": "NIFTY 50",
        "label": "Nifty 50",
        "kite": "NSE:NIFTY 50",
        "db_symbol": "NIFTY50",
        "yf": "^NSEI",
    },
    "nifty100": {
        "nse_name": "NIFTY 100",
        "label": "Nifty 100",
        "kite": "NSE:NIFTY 100",
        "db_symbol": "NIFTY100",
        "yf": "^CNX100",
    },
    "nifty250": {
        "nse_name": "NIFTY MIDCAP 100",
        "label": "Nifty Midcap 100",
        "kite": "NSE:NIFTY MIDCAP 100",
        "db_symbol": "NIFTYMID100",
        "yf": "^NSEMDCP50",
    },
    "market": {
        "nse_name": "NIFTY 500",
        "label": "Nifty 500",
        "kite": "NSE:NIFTY 500",
        "db_symbol": "NIFTY500",
        "yf": "^CRSLDX",
    },
    "banknifty": {
        "nse_name": "NIFTY BANK",
        "label": "Nifty Bank",
        "kite": "NSE:NIFTY BANK",
        "db_symbol": "NIFTYBANK",
        "yf": "^NSEBANK",
    },
    "sensex": {
        "nse_name": "SENSEX",
        "label": "Sensex",
        "kite": "BSE:SENSEX",
        "db_symbol": "SENSEX",
        "yf": "^BSESN",
        "exchange": "BSE",
    },
}

_PERIOD_MAP = {
    "1d": ("1d", "1m"),
    "5d": ("5d", "5m"),
    "1m": ("1mo", "1d"),
    "3m": ("3mo", "1d"),
}


def _kite_interval(interval: str) -> str:
    return {"1m": "minute", "5m": "5minute", "15m": "15minute", "1d": "day"}.get(interval, "5minute")


def _index_token(tradingsymbol: str) -> int | None:
    try:
        from ..data.kite_data_feed import KiteDataFeed

        df = KiteDataFeed().fetch_instruments()
        sym = tradingsymbol.replace("NSE:", "").strip()
        row = df[(df["segment"] == "INDICES") & (df["tradingsymbol"].astype(str) == sym)]
        if row.empty:
            return None
        return int(row.iloc[0]["instrument_token"])
    except Exception:
        logger.exception("index_token_lookup_failed", extra={"symbol": tradingsymbol})
        return None


def _bars_from_kite(index_key: str, *, period: str, interval: str) -> list[dict]:
    from ..ops.healthchecks import check_token

    if not check_token(live=False):
        return []
    meta = INDEX_MAP.get(index_key, INDEX_MAP["nifty50"])
    token = _index_token(meta["kite"])
    if token is None:
        return []
    try:
        from ..data.kite_data_feed import KiteDataFeed

        now = datetime.now(_IST)
        days = {"1d": 1, "5d": 5, "1m": 30, "3m": 90}.get(period, 5)
        start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        df = KiteDataFeed().historical(token, start, end, interval=_kite_interval(interval))
        bars = []
        for _, row in df.iterrows():
            ts = int(row["date"].timestamp())
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            if c <= 0:
                continue
            bars.append({"time": ts, "open": o, "high": h, "low": l, "close": c})
        return bars
    except Exception:
        logger.exception("kite_index_bars_failed", extra={"key": index_key})
        return []


def _bars_from_yahoo(symbol: str, *, period: str = "5d", interval: str = "5m") -> list[dict]:
    import httpx

    yf_period, yf_interval = _PERIOD_MAP.get(period, (period, interval))
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)"}
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url, params={"range": yf_period, "interval": yf_interval}, headers=headers)
            r.raise_for_status()
            result = r.json()["chart"]["result"][0]
            ts = result.get("timestamp") or []
            q = result["indicators"]["quote"][0]
            bars = []
            for i, t in enumerate(ts):
                o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                if None in (o, h, l, c, t):
                    continue
                bars.append({"time": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c)})
            return bars
    except Exception:
        logger.exception("index_yahoo_bars_failed", extra={"symbol": symbol})
        return []


def _nse_spot(nse_name: str) -> dict[str, Any] | None:
    try:
        for row in fetch_nse_all_indices():
            if str(row.get("index", "")).upper() == nse_name.upper():
                return row
    except Exception:
        logger.exception("nse_spot_failed", extra={"index": nse_name})
    return None


def write_index_tick(db, db_symbol: str, ltp: float, *, ts: int | None = None) -> None:
    """Persist index LTP + roll 5m bar in bar_log."""
    now = int(ts or time.time())
    sym = db_symbol
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO tick_log(ts, symbol, ltp) VALUES (?,?,?)",
            (now, sym, ltp),
        )
        bucket = now - (now % 300)
        row = conn.execute(
            "SELECT ts, open, high, low, close FROM bar_log WHERE symbol=? AND interval='5m' AND ts=?",
            (sym, bucket),
        ).fetchone()
        if row:
            hi = max(float(row["high"]), ltp)
            lo = min(float(row["low"]), ltp)
            conn.execute(
                """
                UPDATE bar_log SET high=?, low=?, close=?
                WHERE symbol=? AND interval='5m' AND ts=?
                """,
                (hi, lo, ltp, sym, bucket),
            )
        else:
            conn.execute(
                """
                INSERT INTO bar_log(ts, symbol, interval, open, high, low, close, volume)
                VALUES (?,?,?,?,?,?,?,0)
                """,
                (bucket, sym, "5m", ltp, ltp, ltp, ltp),
            )


def fetch_index_ohlc_from_db(db, symbol: str, interval: str = "5m", *, limit: int = 500) -> list[dict]:
    cur = db._conn.execute(
        """
        SELECT ts, open, high, low, close FROM bar_log
        WHERE symbol=? AND interval=? ORDER BY ts DESC LIMIT ?
        """,
        (symbol, interval, limit),
    )
    rows = [
        {
            "time": int(r["ts"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        for r in cur.fetchall()
    ]
    rows.reverse()
    return rows


def fetch_index_ohlc(
    index_key: str,
    *,
    period: str = "1d",
    interval: str = "5m",
    db=None,
) -> dict[str, Any]:
    """Chart bars — prefer Kite historical, merge NSE live spot, fallback Yahoo/DB."""
    meta = INDEX_MAP.get(index_key, INDEX_MAP["nifty50"])
    bars = _bars_from_kite(index_key, period=period, interval=interval)
    source = f"kite:{meta['kite']}:{interval}"

    if not bars:
        yf_period, yf_iv = _PERIOD_MAP.get(period, (period, interval))
        bars = _bars_from_yahoo(meta["yf"], period=yf_period, interval=yf_iv)
        source = f"yahoo:{meta['yf']}:{yf_iv}"

    if db is not None and len(bars) < 10:
        fb = fetch_index_ohlc_from_db(db, meta["db_symbol"], interval=interval)
        if fb:
            bars = fb
            source = f"db_bar_log:{meta['db_symbol']}"

    spot = _nse_spot(meta["nse_name"])
    change_pct = float(spot["change_pct"]) if spot else None
    last = float(spot["last"]) if spot else (bars[-1]["close"] if bars else None)

    gift = {}
    if index_key == "nifty50":
        try:
            gift = fetch_nse_market_status()
        except Exception:
            pass

    return {
        "index": index_key,
        "label": meta["label"],
        "source": source,
        "bars": bars,
        "bar_count": len(bars),
        "period": period,
        "interval": interval,
        "last": last,
        "change_pct": change_pct,
        "timezone": "Asia/Kolkata",
        "gift_nifty": gift if gift else None,
        "ts": int(time.time()),
    }

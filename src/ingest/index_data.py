"""NSE index OHLC for dashboard charts — Nifty 50/100/500 + broad market."""
from __future__ import annotations

import logging
import time
from typing import Any

from .market_feed_client import fetch_nse_market_status, fetch_yahoo_chart_change_pct

logger = logging.getLogger("bharatquant.index_data")

INDEX_MAP: dict[str, dict[str, str]] = {
    "nifty50": {"nse_name": "NIFTY 50", "label": "Nifty 50", "yf": "^NSEI"},
    "nifty100": {"nse_name": "NIFTY 100", "label": "Nifty 100", "yf": "^CNX100"},
    "nifty250": {"nse_name": "NIFTY MIDCAP 100", "label": "Nifty Midcap 100 (proxy)", "yf": "^NSEMDCP50"},
    "market": {"nse_name": "NIFTY 500", "label": "Nifty 500 (whole market proxy)", "yf": "^CRSLDX"},
}


def _bars_from_yahoo(symbol: str, *, period: str = "5d", interval: str = "5m") -> list[dict]:
    import httpx

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)"}
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url, params={"range": period, "interval": interval}, headers=headers)
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


def fetch_index_ohlc(index_key: str, *, period: str = "5d", interval: str = "5m") -> dict[str, Any]:
    """Chart bars from Yahoo (5m) — full session history; timestamps are UTC unix."""
    meta = INDEX_MAP.get(index_key, INDEX_MAP["nifty50"])
    bars = _bars_from_yahoo(meta["yf"], period=period, interval=interval)
    source = f"yahoo_chart:{meta['yf']}:{interval}"

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
        "timezone": "Asia/Kolkata",
        "gift_nifty": gift if gift else None,
        "ts": int(time.time()),
    }


def fetch_index_ohlc_from_db(db, symbol: str, interval: str = "5m") -> list[dict]:
    cur = db._conn.execute(
        """
        SELECT ts, open, high, low, close FROM bar_log
        WHERE symbol=? AND interval=? ORDER BY ts ASC LIMIT 200
        """,
        (symbol, interval),
    )
    return [
        {
            "time": int(r["ts"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        for r in cur.fetchall()
    ]

"""Reliable market data clients — Kite, NSE India, Yahoo chart API (yfinance library broken)."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("bharatquant.market_feed")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _nse_client() -> httpx.Client:
    return httpx.Client(timeout=25.0, follow_redirects=True, headers=NSE_HEADERS)


def _warm_nse(client: httpx.Client) -> None:
    client.get("https://www.nseindia.com")


def fetch_nse_market_status() -> dict[str, Any]:
    """Real GIFT Nifty + market cap from NSE India (NSE IX futures via marketStatus)."""
    with _nse_client() as client:
        _warm_nse(client)
        r = client.get("https://www.nseindia.com/api/marketStatus")
        r.raise_for_status()
        data = r.json()
    gift = data.get("giftnifty") or {}
    cap = data.get("marketcap") or {}
    per = _parse_pct(gift.get("PERCHANGE", gift.get("perChange", 0)))
    return {
        "gift_last": float(gift.get("LASTPRICE", 0) or 0),
        "gift_change_pct": per,
        "gift_day_change": float(str(gift.get("DAYCHANGE", 0)).replace(",", "") or 0),
        "gift_symbol": gift.get("SYMBOL", "NIFTY"),
        "gift_expiry": gift.get("EXPIRYDATE", ""),
        "gift_timestamp": gift.get("TIMESTMP", ""),
        "market_cap_cr": float(cap.get("marketcapinrrupees", 0) or 0),
        "source": "nse.marketStatus.giftnifty",
    }


def fetch_nse_all_indices() -> list[dict[str, Any]]:
    with _nse_client() as client:
        _warm_nse(client)
        r = client.get("https://www.nseindia.com/api/allIndices")
        r.raise_for_status()
        rows = r.json().get("data", [])
    out = []
    for row in rows:
        out.append(
            {
                "index": row.get("index", ""),
                "last": float(row.get("last", 0) or 0),
                "change_pct": float(row.get("percentChange", 0) or 0),
                "previous_close": float(row.get("previousClose", 0) or 0),
            }
        )
    return out


def fetch_nse_fii_dii() -> dict[str, Any]:
    with _nse_client() as client:
        _warm_nse(client)
        r = client.get("https://www.nseindia.com/api/fiidiiTradeReact")
        r.raise_for_status()
        rows = r.json()
    fii_net = dii_net = 0.0
    date = ""
    for row in rows:
        cat = str(row.get("category", "")).upper()
        net = float(row.get("netValue", 0) or 0)
        date = str(row.get("date", date))
        if "FII" in cat:
            fii_net = net
        elif cat == "DII":
            dii_net = net
    return {
        "fii_net": fii_net,
        "dii_net": dii_net,
        "date": date,
        "source": "nse.fiidiiTradeReact",
    }


def _parse_pct(val: Any) -> float:
    try:
        return float(str(val).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def fetch_yahoo_chart_change_pct(symbol: str, *, range_: str = "5d", interval: str = "1d") -> float | None:
    """Direct Yahoo chart API — works when yfinance library fails."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_, "interval": interval}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BharatQuant/1.0)"}
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url, params=params, headers=headers)
            r.raise_for_status()
            result = r.json()["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if len(closes) < 2:
                return None
            c0, c1 = float(closes[-2]), float(closes[-1])
            if c0 <= 0:
                return None
            return (c1 - c0) / c0 * 100.0
    except Exception:
        logger.exception("yahoo_chart_failed", extra={"symbol": symbol})
        return None


def fetch_kite_snapshot() -> dict[str, float]:
    """Indian indices + FX + crude via existing Kite token."""
    from kiteconnect import KiteConnect

    from ..feeds.kite_ticker import load_access_token

    api_key, token = load_access_token()
    k = KiteConnect(api_key=api_key)
    k.set_access_token(token)

    keys = ["NSE:NIFTY 50", "NSE:INDIA VIX", "NSE:NIFTY 100", "NSE:NIFTY 500"]
    try:
        for seg, prefix in (("CDS", "USDINR"), ("MCX", "CRUDEOIL")):
            inst = k.instruments(seg)
            fut = sorted(
                [i for i in inst if i["tradingsymbol"].startswith(prefix) and i["instrument_type"] == "FUT"],
                key=lambda x: x["expiry"],
            )
            if fut:
                keys.append(f"{seg}:{fut[0]['tradingsymbol']}")
    except Exception:
        logger.exception("kite_fut_lookup_failed")

    out: dict[str, float] = {}
    try:
        quotes = k.quote(keys)
    except Exception:
        logger.exception("kite_snapshot_failed")
        return out

    def _session_chg(key: str) -> float:
        q = quotes.get(key, {})
        ohlc = q.get("ohlc") or {}
        close = float(ohlc.get("close") or 0)
        last = float(q.get("last_price") or 0)
        if close > 0 and last > 0:
            return (last - close) / close * 100.0
        return 0.0

    if "NSE:NIFTY 50" in quotes:
        out["nifty50_change_pct"] = _session_chg("NSE:NIFTY 50")
    if "NSE:INDIA VIX" in quotes:
        q = quotes["NSE:INDIA VIX"]
        out["india_vix"] = float(q.get("last_price") or 0)
    if "NSE:NIFTY 100" in quotes:
        out["nifty100_change_pct"] = _session_chg("NSE:NIFTY 100")
    if "NSE:NIFTY 500" in quotes:
        out["nifty500_change_pct"] = _session_chg("NSE:NIFTY 500")
    for key in keys:
        if key.startswith("CDS:USDINR"):
            out["usd_inr"] = _session_chg(key)
        if key.startswith("MCX:CRUDEOIL"):
            out["crude"] = _session_chg(key)
    out["source"] = "kite.quote"
    return out


def fetch_global_macro_bundle() -> dict[str, float]:
    """US futures + crude + FX + India VIX with multi-source fallback."""
    out: dict[str, float] = {}

    kite = fetch_kite_snapshot()
    if kite.get("india_vix"):
        out["india_vix"] = kite["india_vix"]
    if kite.get("usd_inr") is not None:
        out["usd_inr"] = kite["usd_inr"]
    if kite.get("crude") is not None:
        out["crude"] = kite["crude"]

    us = fetch_yahoo_chart_change_pct("ES=F")
    if us is not None:
        out["us_sp"] = us
    elif kite.get("nifty50_change_pct") is not None:
        out["us_sp"] = kite["nifty50_change_pct"] * 0.85

    if "crude" not in out:
        cl = fetch_yahoo_chart_change_pct("CL=F")
        if cl is not None:
            out["crude"] = cl

    if "usd_inr" not in out:
        fx = fetch_yahoo_chart_change_pct("USDINR=X")
        if fx is not None:
            out["usd_inr"] = fx

    if "india_vix" not in out:
        # Yahoo returns % change — store separately; never substitute for VIX level
        vix_chg = fetch_yahoo_chart_change_pct("^INDIAVIX")
        if vix_chg is not None:
            out["india_vix_change_pct"] = vix_chg

    us_vix = fetch_yahoo_chart_change_pct("^VIX")
    if us_vix is not None:
        out["us_vix_chg"] = us_vix
    nikkei = fetch_yahoo_chart_change_pct("^N225")
    if nikkei is not None:
        out["nikkei_chg"] = nikkei
    hsi = fetch_yahoo_chart_change_pct("^HSI")
    if hsi is not None:
        out["hang_seng_chg"] = hsi

    if not out:
        raise RuntimeError("global_macro_bundle empty — all providers failed")
    out["fetched_ts"] = time.time()
    return out

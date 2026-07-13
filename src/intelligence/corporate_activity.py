"""Corporate & mass-market activity — insider, bulk/block, dividends, promoter moves."""
from __future__ import annotations

import json
import time
from typing import Any

from ..db.database import DB

_DIVIDEND_KW = ("dividend", "interim dividend", "final dividend", "record date", "ex-date", "ex date")
_PROMOTER_KW = ("promoter", "promoter group", "increase stake", "acquisition of shares", "pledge")
_INSIDER_KW = ("insider", "pit", "disclosure", "acquisition", "sale of shares")
_EARNINGS_KW = ("result", "earnings", "quarter", "financial", "profit", "revenue")
_RIGHTS_KW = ("rights issue", "rights entitlement", "preferential")


def classify_corp_category(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in _DIVIDEND_KW):
        return "dividend"
    if any(k in t for k in _RIGHTS_KW):
        return "rights"
    if any(k in t for k in _EARNINGS_KW):
        return "earnings"
    if any(k in t for k in _PROMOTER_KW):
        return "promoter"
    if any(k in t for k in _INSIDER_KW):
        return "insider"
    return "corporate"


def normalize_insider(row: dict) -> dict[str, Any]:
    person = str(row.get("personName", row.get("acquirerName", "")) or "")
    acq = str(row.get("acqMode", row.get("buySell", row.get("transactionType", ""))) or "")
    side = "buy" if any(x in acq.lower() for x in ("buy", "acq", "purchase")) else "sell"
    is_promoter = "promoter" in person.lower()
    return {
        "kind": "insider",
        "category": "promoter" if is_promoter else "insider",
        "symbol": str(row.get("symbol", "")).replace("NSE:", ""),
        "person": person,
        "side": side,
        "qty": row.get("secAcq", row.get("quantity", row.get("qty"))),
        "price": row.get("avgPrice", row.get("price")),
        "date": row.get("acqfromDt", row.get("date", "")),
        "reason": f"{person} {side} — {acq}".strip(" —"),
        "why": "Regulatory PIT filing (NSE corporates-pit)",
    }


def normalize_bulk(row: dict) -> dict[str, Any]:
    client = str(row.get("clientName", row.get("buyer", row.get("seller", ""))) or "")
    side_raw = str(row.get("buySell", row.get("side", "")) or "").lower()
    side = "buy" if "buy" in side_raw or "acq" in side_raw else "sell"
    sym = str(row.get("symbol", "")).replace("NSE:", "")
    qty = float(row.get("qty", row.get("quantity", 0)) or 0)
    return {
        "kind": "bulk",
        "category": "block_deal",
        "symbol": sym,
        "client": client,
        "side": side,
        "qty": qty,
        "price": float(row.get("price", row.get("wap", 0)) or 0),
        "date": row.get("date", row.get("tradedDate", "")),
        "reason": f"{client or 'Institution'} {side} {int(qty):,} shares",
        "why": "NSE large deal (bulk/block snapshot)",
    }


def normalize_corp_announce(row: dict) -> dict[str, Any]:
    desc = str(row.get("desc", row.get("subject", row.get("attchmntText", ""))) or "")
    sym = str(row.get("symbol", row.get("sm_name", ""))).replace("NSE:", "")
    cat = classify_corp_category(desc)
    return {
        "kind": "announcement",
        "category": cat,
        "symbol": sym,
        "title": desc[:240],
        "date": row.get("an_dt", row.get("sort_date", "")),
        "reason": desc[:160],
        "why": _why_for_category(cat),
    }


def _why_for_category(cat: str) -> str:
    return {
        "dividend": "Board/corporate action — income event for holders",
        "promoter": "Promoter/promoter-group stake change — alignment signal",
        "insider": "Insider transaction disclosure",
        "earnings": "Financial results — volatility/event risk",
        "rights": "Capital raise — dilution/watchlist flag",
        "corporate": "Exchange filing — review before sizing",
    }.get(cat, "Corporate filing")


def _rows_from_ingest(db: DB, event_type: str, *, limit: int = 40, since_ts: int = 0) -> list[dict]:
    rows = db._conn.execute(
        """
        SELECT ts, payload_json FROM ingest_log
        WHERE event_type=? AND ts >= ?
        ORDER BY ts DESC LIMIT ?
        """,
        (event_type, since_ts, limit),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        try:
            p = json.loads(r["payload_json"])
            p["_ts"] = int(r["ts"])
            out.append(p)
        except json.JSONDecodeError:
            continue
    return out


def load_corporate_activity(db: DB, *, lookback_days: int = 7) -> dict[str, Any]:
    """Unified snapshot for agent + dashboard — who did what, when, and why."""
    since = int(time.time()) - lookback_days * 86400
    insider_raw = _rows_from_ingest(db, "INSIDER_FILING", limit=30, since_ts=since)
    bulk_raw = _rows_from_ingest(db, "BLOCK_DEAL", limit=30, since_ts=since)
    corp_raw = _rows_from_ingest(db, "NEWS_ALERT", limit=40, since_ts=since)
    fii_raw = _rows_from_ingest(db, "FII_DII_UPDATE", limit=5, since_ts=since)

    insider = [normalize_insider(r) for r in insider_raw]
    bulk = [normalize_bulk(r) for r in bulk_raw]
    announcements = [normalize_corp_announce(r) for r in corp_raw]

    dividends = [a for a in announcements if a["category"] == "dividend"]
    promoter_moves = [i for i in insider if i["category"] == "promoter" or "promoter" in i.get("person", "").lower()]
    promoter_moves += [a for a in announcements if a["category"] == "promoter"]

    mass_flow: list[dict] = []
    for r in fii_raw:
        mass_flow.append(
            {
                "kind": "mass_flow",
                "category": "fii_dii",
                "date": r.get("date", ""),
                "fii_net_cr": r.get("fii_net", r.get("fii_net_cr")),
                "dii_net_cr": r.get("dii_net", r.get("dii_net_cr")),
                "reason": (
                    f"FII net {r.get('fii_net', r.get('fii_net_cr', 0))} cr, "
                    f"DII net {r.get('dii_net', r.get('dii_net_cr', 0))} cr"
                ),
                "why": "Exchange-wide institutional flow (mass market positioning)",
            }
        )

    timeline: list[dict] = []
    for r in insider_raw:
        n = normalize_insider(r)
        n["ts"] = int(r.get("_ts", 0))
        timeline.append(n)
    for r in bulk_raw:
        n = normalize_bulk(r)
        n["ts"] = int(r.get("_ts", 0))
        timeline.append(n)
    for r in corp_raw:
        n = normalize_corp_announce(r)
        n["ts"] = int(r.get("_ts", 0))
        timeline.append(n)
    timeline.sort(key=lambda x: x.get("ts", 0), reverse=True)
    timeline = timeline[:25]

    return {
        "ts": int(time.time()),
        "lookback_days": lookback_days,
        "counts": {
            "insider": len(insider),
            "bulk": len(bulk),
            "announcements": len(announcements),
            "dividends": len(dividends),
            "promoter": len(promoter_moves),
            "mass_flow": len(mass_flow),
        },
        "insider": insider[:12],
        "bulk": bulk[:12],
        "dividends": dividends[:8],
        "promoter_moves": promoter_moves[:8],
        "announcements": announcements[:15],
        "mass_flow": mass_flow[:3],
        "timeline": timeline,
    }


def corporate_profit_tilt(symbol: str, ctx: Any) -> tuple[float, list[str]]:
    """Map corporate/mass-market signals → expected-profit multiplier for a symbol."""
    sym = str(symbol or "").replace("NSE:", "")
    mult = 1.0
    reasons: list[str] = []

    promoter_watch = list(getattr(ctx, "promoter_watch", None) or [])
    dividend_watch = list(getattr(ctx, "dividend_watch", None) or [])
    recent = list(getattr(ctx, "recent_corporate", None) or [])

    if sym in promoter_watch:
        mult *= 1.14
        reasons.append("promoter_stake_up")
    if sym in dividend_watch:
        mult *= 1.08
        reasons.append("dividend_income")

    for ev in recent[:15]:
        if str(ev.get("symbol", "")).replace("NSE:", "") != sym:
            continue
        cat = str(ev.get("category", ""))
        side = str(ev.get("side", ""))
        kind = str(ev.get("kind", ""))
        if kind in ("insider",) or cat == "promoter":
            if side == "buy":
                mult *= 1.1
                reasons.append("insider_buy")
            elif side == "sell":
                mult *= 0.72
                reasons.append("insider_sell")
        elif kind == "bulk":
            if side == "buy":
                mult *= 1.08
                reasons.append("bulk_buy")
            elif side == "sell":
                mult *= 0.85
                reasons.append("bulk_sell")
        elif cat == "dividend":
            mult *= 1.06
            reasons.append("dividend_catalyst")

    return min(1.35, max(0.55, mult)), reasons


def corporate_narrative_lines(snapshot: dict) -> list[str]:
    lines: list[str] = []
    c = snapshot.get("counts", {})
    if c.get("mass_flow"):
        mf = (snapshot.get("mass_flow") or [{}])[0]
        fii = float(mf.get("fii_net_cr") or 0)
        cue = "risk-on tailwind for longs" if fii > 200 else "caution on fresh longs" if fii < -200 else "mixed flow"
        lines.append(f"Profit context — mass market ({cue}): {mf.get('reason', 'FII/DII update')}.")
    if c.get("promoter"):
        pm = (snapshot.get("promoter_moves") or [{}])[0]
        lines.append(
            f"Profit cue — promoter buy {pm.get('symbol', '?')}: "
            f"{pm.get('reason', pm.get('title', 'filing'))}; alignment signal for entry/hold."
        )
    if c.get("insider"):
        ins = (snapshot.get("insider") or [{}])[0]
        action = "favour longs" if ins.get("side") == "buy" else "trim/avoid longs"
        lines.append(f"Profit cue — insider {ins.get('symbol', '?')}: {ins.get('reason', '')} → {action}.")
    if c.get("bulk"):
        b = (snapshot.get("bulk") or [{}])[0]
        action = "follow smart money in" if b.get("side") == "buy" else "distribution risk"
        lines.append(f"Profit cue — block deal {b.get('symbol', '?')}: {b.get('reason', '')} → {action}.")
    if c.get("dividends"):
        d = (snapshot.get("dividends") or [{}])[0]
        lines.append(
            f"Income opportunity — dividend {d.get('symbol', '?')}: "
            f"{(d.get('title') or d.get('reason', ''))[:80]}; capture yield before ex-date."
        )
    if not lines:
        lines.append(
            "Profit scan: no insider/bulk/dividend edge in 7-day window — defaulting to momentum + cost-edge gates."
        )
    return lines

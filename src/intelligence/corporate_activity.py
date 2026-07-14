"""Corporate & mass-market activity — insider, bulk/block, dividends, promoter moves."""
from __future__ import annotations

import json
import time
from typing import Any

from ..db.database import DB
from ..intelligence.institutional_entities import classify_entity

_DIVIDEND_KW = ("dividend", "interim dividend", "final dividend", "record date", "ex-date", "ex date")
_PROMOTER_KW = ("promoter", "promoter group", "increase stake", "acquisition of shares", "pledge")
_INSIDER_KW = ("insider", "pit", "disclosure", "acquisition", "sale of shares")
_EARNINGS_KW = ("result", "earnings", "quarter", "financial", "profit", "revenue")
_RIGHTS_KW = ("rights issue", "rights entitlement", "preferential")


_SPLIT_KW = ("stock split", "sub-division", "subdivision", "face value")
_BONUS_KW = ("bonus issue", "bonus shares", "bonus equity")
_BUYBACK_KW = ("buyback", "buy-back", "share repurchase", "repurchase of shares")
_MERGER_KW = ("merger", "amalgamation", "demerger", "scheme of arrangement")
_DELIST_KW = ("delist", "delisting", "exit from exchange")


def classify_corp_category(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in _DIVIDEND_KW):
        return "dividend"
    if any(k in t for k in _BONUS_KW):
        return "bonus"
    if any(k in t for k in _SPLIT_KW):
        return "split"
    if any(k in t for k in _BUYBACK_KW):
        return "buyback"
    if any(k in t for k in _MERGER_KW):
        return "merger"
    if any(k in t for k in _DELIST_KW):
        return "delisting"
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
    entity = str(row.get("entity_class", "")) or classify_entity(client)
    return {
        "kind": "bulk",
        "category": "block_deal",
        "symbol": sym,
        "client": client,
        "entity_class": entity,
        "side": side,
        "qty": qty,
        "price": float(row.get("price", row.get("wap", 0)) or 0),
        "date": row.get("date", row.get("tradedDate", "")),
        "reason": f"{client or entity.upper()} {side} {int(qty):,} shares",
        "why": f"NSE large deal — {entity} flow",
    }


def normalize_shareholding(row: dict) -> dict[str, Any]:
    sym = str(row.get("symbol", "")).replace("NSE:", "")
    deltas = row.get("deltas") or {}
    mf_d = float(deltas.get("mf_pct") or deltas.get("institutional_pct") or 0)
    fii_d = float(deltas.get("fii_pct") or 0)
    pub_d = float(deltas.get("public_pct") or 0)
    prom_d = float(deltas.get("promoter_pct") or 0)
    side = "buy" if mf_d > 0 or fii_d > 0 or pub_d > 0 or prom_d > 0 else "sell" if mf_d < 0 or pub_d < 0 or prom_d < 0 else "neutral"
    return {
        "kind": "shareholding",
        "category": "shareholding",
        "symbol": sym,
        "side": side,
        "entity_class": "mf" if abs(mf_d) >= abs(fii_d) else "fii",
        "mf_pct": row.get("mf_pct"),
        "fii_pct": row.get("fii_pct"),
        "promoter_pct": row.get("promoter_pct"),
        "public_pct": row.get("public_pct"),
        "deltas": deltas,
        "as_of_date": row.get("as_of_date", ""),
        "reason": (
            f"SHP {sym}: promoter {prom_d:+.2f}%, public {pub_d:+.2f}%, "
            f"inst {mf_d:+.2f}% QoQ"
        ),
        "why": "NSE quarterly shareholding pattern — institutional stake change",
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
    shp_raw = _rows_from_ingest(db, "SHAREHOLDING_UPDATE", limit=20, since_ts=since - 90 * 86400)
    mf_raw = _rows_from_ingest(db, "MF_HOLDING_UPDATE", limit=20, since_ts=since)

    insider = [normalize_insider(r) for r in insider_raw]
    bulk = [normalize_bulk(r) for r in bulk_raw]
    announcements = [normalize_corp_announce(r) for r in corp_raw]
    shareholding = [normalize_shareholding(r) for r in shp_raw]
    mf_flows = [
        normalize_bulk(r) if r.get("clientName") else {
            "kind": "mf_flow",
            "category": "mf_holding",
            "symbol": str(r.get("symbol", "")).replace("NSE:", ""),
            "client": r.get("client", ""),
            "entity_class": "mf",
            "side": r.get("side", "buy"),
            "qty": r.get("qty"),
            "reason": f"MF {r.get('client', 'fund')} {r.get('side', 'buy')}",
            "why": "MF block-flow (classified bulk client)",
        }
        for r in mf_raw
    ]

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
    for r in shp_raw:
        n = normalize_shareholding(r)
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
            "shareholding": len(shareholding),
            "mf_flows": len(mf_flows),
        },
        "insider": insider[:12],
        "bulk": bulk[:12],
        "dividends": dividends[:8],
        "promoter_moves": promoter_moves[:8],
        "announcements": announcements[:15],
        "mass_flow": mass_flow[:3],
        "shareholding": shareholding[:8],
        "mf_flows": mf_flows[:8],
        "timeline": timeline,
    }


def corporate_profit_tilt(symbol: str, ctx: Any) -> tuple[float, list[str]]:
    """
    Map NSE public disclosure signals → sizing multiplier from learned institutional outcomes.
    Data: PIT filings, bulk/block deals, shareholding — all public regulatory sources.
    No hardcoded tilt constants; multipliers come from labeled corporate_event_outcomes only.
    """
    from .institutional_learning import load_institutional_weights, pattern_multiplier

    sym = str(symbol or "").replace("NSE:", "")
    mult = 1.0
    reasons: list[str] = []

    weights = getattr(ctx, "institutional_weights", None)
    if not weights:
        db = getattr(ctx, "db", None)
        if db is not None:
            weights = load_institutional_weights(db)
        else:
            weights = {}

    recent = list(getattr(ctx, "recent_corporate", None) or [])

    for ev in recent[:15]:
        if str(ev.get("symbol", "")).replace("NSE:", "") != sym:
            continue
        cat = str(ev.get("category", ""))
        side = str(ev.get("side", ""))
        kind = str(ev.get("kind", ""))
        entity = str(ev.get("entity_class", "other"))
        et = {
            "insider": "INSIDER_FILING",
            "bulk": "BLOCK_DEAL",
            "shareholding": "SHAREHOLDING_UPDATE",
            "mf_flow": "MF_HOLDING_UPDATE",
        }.get(kind, "NEWS_ALERT")
        lm, lr = pattern_multiplier(weights, event_type=et, category=cat, side=side, entity_class=entity)
        if lm != 1.0:
            mult *= lm
            if lr:
                reasons.append(lr)

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
    if c.get("shareholding"):
        sh = (snapshot.get("shareholding") or [{}])[0]
        lines.append(
            f"Profit cue — shareholding {sh.get('symbol', '?')}: "
            f"{sh.get('reason', '')}; MF/FII stake change → follow institutional drift."
        )
    if c.get("mf_flows"):
        mf = (snapshot.get("mf_flows") or [{}])[0]
        lines.append(f"Profit cue — MF flow {mf.get('symbol', '?')}: {mf.get('reason', '')}.")
    if not lines:
        lines.append(
            "Profit scan: no insider/bulk/dividend edge in 7-day window — defaulting to momentum + cost-edge gates."
        )
    return lines

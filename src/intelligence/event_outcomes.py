"""Label corporate events with +5d/+20d forward returns — feeds RL + bandit."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..db.database import DB
from ..events.types import EventType
from ..intelligence.corporate_activity import (
    classify_corp_category,
    normalize_bulk,
    normalize_corp_announce,
    normalize_insider,
)
from ..intelligence.institutional_entities import classify_entity

logger = logging.getLogger("bharatquant.event_outcomes")

_D5_SEC = 7 * 86400
_D20_SEC = 28 * 86400
_LABELABLE = frozenset(
    {
        EventType.INSIDER_FILING,
        EventType.BLOCK_DEAL,
        EventType.NEWS_ALERT,
        EventType.SHAREHOLDING_UPDATE,
        EventType.MF_HOLDING_UPDATE,
        EventType.CORPORATE_ACTION,
        EventType.BOARD_MEETING,
        EventType.EVENT_CALENDAR,
        EventType.BSE_ANNOUNCEMENT,
    }
)


def _price_near(db: DB, symbol: str, ts: int, *, window: int = 7200) -> float | None:
    sym = symbol.replace("NSE:", "")
    row = db._conn.execute(
        """
        SELECT ltp FROM tick_log
        WHERE symbol=? AND ts BETWEEN ? AND ?
        ORDER BY ABS(ts - ?) LIMIT 1
        """,
        (sym, ts - window, ts + window, ts),
    ).fetchone()
    if row:
        return float(row["ltp"])
    row = db._conn.execute(
        """
        SELECT close FROM bar_log WHERE symbol=? AND ts <= ? ORDER BY ts DESC LIMIT 1
        """,
        (sym, ts + window),
    ).fetchone()
    if row:
        return float(row["close"])
    row = db._conn.execute(
        """
        SELECT ltp FROM tick_log WHERE symbol=? AND ts <= ? ORDER BY ts DESC LIMIT 1
        """,
        (sym, ts + window),
    ).fetchone()
    return float(row["ltp"]) if row else None


def _forward_return(db: DB, symbol: str, entry_ts: int, entry_price: float, horizon_sec: int) -> float | None:
    if entry_price <= 0:
        return None
    exit_ts = entry_ts + horizon_sec
    exit_price = _price_near(db, symbol, exit_ts, window=3 * 86400)
    if exit_price is None or exit_price <= 0:
        return None
    return (exit_price - entry_price) / entry_price * 100.0


def _normalize_event(event_type: str, payload: dict) -> dict[str, Any]:
    et = str(event_type)
    if et == EventType.INSIDER_FILING:
        n = normalize_insider(payload)
    elif et == EventType.BLOCK_DEAL:
        n = normalize_bulk(payload)
    elif et == EventType.SHAREHOLDING_UPDATE:
        n = {
            "kind": "shareholding",
            "category": "shareholding",
            "symbol": str(payload.get("symbol", "")).replace("NSE:", ""),
            "side": "buy" if float((payload.get("deltas") or {}).get("mf_pct") or 0) > 0 else "neutral",
            "entity_class": "mf",
        }
    elif et == EventType.MF_HOLDING_UPDATE:
        n = {
            "kind": "mf_flow",
            "category": "mf_holding",
            "symbol": str(payload.get("symbol", "")).replace("NSE:", ""),
            "side": str(payload.get("side", "buy")),
            "entity_class": "mf",
            "client": payload.get("client", ""),
        }
    elif et in (EventType.CORPORATE_ACTION, EventType.BOARD_MEETING, EventType.EVENT_CALENDAR, EventType.BSE_ANNOUNCEMENT):
        text = " ".join(str(payload.get(k, "")) for k in ("desc", "subject", "purpose", "title", "summary"))
        n = {
            "kind": str(et).lower(),
            "category": classify_corp_category(text) if text.strip() else str(et).lower(),
            "symbol": str(payload.get("symbol", payload.get("sm_name", ""))).replace("NSE:", ""),
            "side": "neutral",
            "entity_class": "exchange",
        }
    else:
        n = normalize_corp_announce(payload)
    if not n.get("entity_class"):
        client = str(n.get("client", n.get("person", "")))
        n["entity_class"] = classify_entity(client)
    return n


def label_pending_events(db: DB, *, now: int | None = None) -> dict[str, int]:
    """Scan ingest_log → corporate_event_outcomes with forward returns."""
    now = now or int(time.time())
    rows = db._conn.execute(
        f"""
        SELECT il.ts, il.event_type, il.payload_json
        FROM ingest_log il
        WHERE il.event_type IN ({",".join("?" * len(_LABELABLE))})
          AND il.ts < ?
        ORDER BY il.ts ASC
        LIMIT 800
        """,
        (*tuple(_LABELABLE), now - _D5_SEC),
    ).fetchall()

    labeled = 0
    skipped = 0
    for row in rows:
        event_ts = int(row["ts"])
        event_type = str(row["event_type"])
        if event_type not in _LABELABLE:
            continue
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            skipped += 1
            continue
        norm = _normalize_event(event_type, payload)
        sym = str(norm.get("symbol", "")).replace("NSE:", "")
        if not sym:
            skipped += 1
            continue
        cat = str(norm.get("category", classify_corp_category(str(payload.get("desc", "")))))
        exists = db._conn.execute(
            """
            SELECT id FROM corporate_event_outcomes
            WHERE event_ts=? AND symbol=? AND event_type=? AND category=?
            """,
            (event_ts, sym, event_type, cat),
        ).fetchone()
        if exists:
            continue

        entry = _price_near(db, sym, event_ts)
        if entry is None or entry <= 0:
            entry = float(payload.get("price", payload.get("avgPrice", 0)) or 0)
        if entry <= 0:
            skipped += 1
            continue

        ret_5d = _forward_return(db, sym, event_ts, entry, _D5_SEC) if now >= event_ts + _D5_SEC else None
        ret_20d = _forward_return(db, sym, event_ts, entry, _D20_SEC) if now >= event_ts + _D20_SEC else None
        if ret_5d is None and ret_20d is None:
            skipped += 1
            continue

        with db.tx() as conn:
            conn.execute(
                """
                INSERT INTO corporate_event_outcomes(
                  event_ts, symbol, event_type, category, side, entity_class,
                  entry_price, ret_5d, ret_20d, labeled_ts
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(event_ts, symbol, event_type, category) DO UPDATE SET
                  ret_5d=COALESCE(excluded.ret_5d, ret_5d),
                  ret_20d=COALESCE(excluded.ret_20d, ret_20d),
                  labeled_ts=excluded.labeled_ts
                """,
                (
                    event_ts,
                    sym,
                    event_type,
                    cat,
                    norm.get("side"),
                    norm.get("entity_class"),
                    entry,
                    ret_5d,
                    ret_20d,
                    now,
                ),
            )
        labeled += 1

    logger.info("event_outcomes_labeled", extra={"labeled": labeled, "skipped": skipped})
    return {"labeled": labeled, "skipped": skipped}

"""Market news digest from NSE/BSE exchange filings — feeds LLM + dashboard."""
from __future__ import annotations

import json
from typing import Any

from ..events.types import EventType

_NEWS_TYPES = (
    EventType.NEWS_ALERT,
    EventType.BSE_ANNOUNCEMENT,
    EventType.BOARD_MEETING,
    EventType.CORPORATE_ACTION,
    EventType.EVENT_CALENDAR,
)


def recent_market_headlines(db, *, limit: int = 12, hours: int = 48) -> list[dict[str, Any]]:
    """Pull recent exchange-sourced headlines from ingest_log."""
    cutoff = int(__import__("time").time()) - hours * 3600
    placeholders = ",".join("?" * len(_NEWS_TYPES))
    rows = db._conn.execute(
        f"""
        SELECT ts, event_type, payload_json FROM ingest_log
        WHERE event_type IN ({placeholders}) AND ts >= ?
        ORDER BY ts DESC LIMIT ?
        """,
        (*_NEWS_TYPES, cutoff, limit * 2),
    ).fetchall()

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            p = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            continue
        title = str(
            p.get("title")
            or p.get("desc")
            or p.get("subject")
            or p.get("purpose")
            or p.get("summary")
            or ""
        ).strip()[:200]
        if not title or title in seen:
            continue
        seen.add(title)
        sym = str(p.get("symbol", p.get("sm_name", ""))).replace("NSE:", "")
        out.append({
            "ts": int(row["ts"]),
            "event_type": str(row["event_type"]),
            "symbol": sym,
            "title": title,
            "source": str(p.get("source", row["event_type"])),
        })
        if len(out) >= limit:
            break
    return out


def headline_titles(db, *, limit: int = 10) -> list[str]:
    return [h["title"] for h in recent_market_headlines(db, limit=limit)]

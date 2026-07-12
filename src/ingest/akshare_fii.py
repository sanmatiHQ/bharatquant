"""akshare supplemental FII/DII — SIGNAL_ONLY, optional dependency."""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ..data.provenance import record_ingest, tag_payload
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.ingest.akshare_fii")

SOURCE = "akshare.stock_em_fund_flow"


def _fetch_akshare() -> Optional[dict[str, Any]]:
    try:
        import akshare as ak
    except ImportError:
        logger.debug("akshare_not_installed")
        return None
    try:
        if hasattr(ak, "stock_hsgt_fund_flow_summary_em"):
            df = ak.stock_hsgt_fund_flow_summary_em()
            if df is not None and not df.empty:
                row = df.iloc[-1]
                return {
                    "fii_net": float(row.get("资金净流入", row.get("净流入", 0)) or 0),
                    "source_feed": "akshare",
                    "date": str(row.get("日期", "")),
                }
        return None
    except Exception:
        logger.exception("akshare_fii_fetch_error")
        return None


async def poll_akshare_fii(publish: Callable, interval_sec: float = 600.0, db=None) -> None:
    import asyncio

    last = ""
    while True:
        row = await asyncio.to_thread(_fetch_akshare)
        if row:
            d = str(row.get("date", ""))
            if d != last:
                last = d
                payload = tag_payload(row, source=SOURCE, execution_allowed=False)
                await publish(MarketEvent(type=EventType.FII_DII_UPDATE, payload=payload))
                if db is not None:
                    with db.tx() as conn:
                        record_ingest(
                            conn,
                            source=SOURCE,
                            event_type=EventType.FII_DII_UPDATE,
                            payload=payload,
                            execution_allowed=False,
                        )
                logger.info("akshare_fii_published", extra=row)
        await asyncio.sleep(interval_sec)

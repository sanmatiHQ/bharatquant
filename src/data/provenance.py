"""
Ingest provenance — every non-Kite row tagged for audit (QuantFinance-Databases pattern).

Verified against cporter202 webhook metadata + our data_policy execution gate.
"""
from __future__ import annotations

import json
import time
from typing import Any

# Kite Connect is the only execution-grade price source.
KITE_SOURCE = "kite_connect"
SIGNAL_ONLY = False
EXECUTION_ALLOWED = True


def tag_payload(
    data: dict[str, Any],
    *,
    source: str,
    execution_allowed: bool,
) -> dict[str, Any]:
    """Merge provenance fields into ingest/strategy payloads."""
    return {
        **data,
        "source": source,
        "fetched_at": int(time.time()),
        "execution_allowed": execution_allowed,
    }


def record_ingest(
    conn,
    *,
    source: str,
    event_type: str,
    payload: dict[str, Any],
    execution_allowed: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO ingest_log(ts, source, event_type, payload_json, execution_allowed)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            int(time.time()),
            source,
            event_type,
            json.dumps(payload, default=str),
            1 if execution_allowed else 0,
        ),
    )

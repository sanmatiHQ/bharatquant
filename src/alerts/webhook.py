"""
Signed outbound alerts — pattern from cporter202/stock-market-signal-automation.

Used for Telegram / webhook consumers; strategy signals are replayable by delivery_id.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

import httpx


def _sign(raw_body: bytes, timestamp_ms: str, secret: str) -> str:
    signed = timestamp_ms.encode("utf-8") + b"." + raw_body
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def build_delivery(
    event: str,
    data: dict[str, Any],
    *,
    secret: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    delivery_id = str(uuid.uuid4())
    ts_ms = str(int(time.time() * 1000))
    body = {
        "event": event,
        "delivery_id": delivery_id,
        "sent_at": ts_ms,
        "data": data,
    }
    raw = json.dumps(body, separators=(",", ":"), default=str).encode("utf-8")
    headers = {
        "X-BharatQuant-Event": event,
        "X-BharatQuant-Delivery": delivery_id,
        "X-BharatQuant-Timestamp": ts_ms,
        "Content-Type": "application/json",
    }
    sec = secret or os.getenv("ALERT_SIGNING_SECRET", "")
    if sec:
        headers["X-BharatQuant-Signature"] = _sign(raw, ts_ms, sec)
    return body, headers


async def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json={"chat_id": chat_id, "text": text[:4000]})
        return r.is_success


async def publish_strategy_alert(
    strategy_id: str,
    symbol: str,
    action: str,
    confidence: float,
    reason: str,
) -> None:
    body, _headers = build_delivery(
        "strategy.signal",
        {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "reason": reason,
        },
    )
    line = (
        f"[{body['event']}] {action} {symbol} "
        f"conf={confidence:.2f} id={body['delivery_id'][:8]} — {reason}"
    )
    await send_telegram(line)

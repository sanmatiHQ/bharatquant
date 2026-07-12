"""TOKEN_EXPIRED / WS_AUTH_FAIL → headless re-auth."""
from __future__ import annotations

import asyncio
import logging
import os

from ..alerts.webhook import send_telegram
from ..events.types import EventType, MarketEvent

logger = logging.getLogger("bharatquant.auth_recovery")


async def handle_auth_event(event: MarketEvent, *, restart_feed: callable | None = None) -> bool:
    if event.type not in (EventType.TOKEN_EXPIRED, EventType.WS_AUTH_FAIL):
        return False
    user = os.getenv("KITE_USER_ID", "")
    pwd = os.getenv("KITE_PASSWORD", "")
    totp = os.getenv("KITE_TOTP_SECRET", "")
    api_key = os.getenv("KITE_API_KEY", "")
    token_file = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
    if not all([user, pwd, totp, api_key]):
        logger.error("auth_recovery_missing_creds")
        await send_telegram(f"AUTH FAIL {event.type} — creds missing")
        return False
    try:
        from ..auth.kite_totp import headless_login

        await headless_login(user, pwd, totp, api_key, token_file)
        logger.info("auth_recovery_ok")
        await send_telegram(f"AUTH RECOVERED after {event.type}")
        if restart_feed:
            restart_feed()
        return True
    except Exception:
        logger.exception("auth_recovery_failed")
        await send_telegram(f"AUTH RECOVERY FAILED {event.type}")
        return False


async def poll_token_health(publish, interval_sec: float = 600.0) -> None:
    """Probe token file age; publish TOKEN_EXPIRED if stale."""
    import time
    from pathlib import Path

    path = Path(os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json"))
    while True:
        try:
            if path.exists():
                age_h = (time.time() - path.stat().st_mtime) / 3600
                if age_h > 20:
                    await publish(MarketEvent(type=EventType.TOKEN_EXPIRED, payload={"age_h": age_h}))
        except Exception:
            logger.exception("token_health_error")
        await asyncio.sleep(interval_sec)

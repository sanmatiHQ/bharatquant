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
    from ..ops.healthchecks import check_token

    # Dashboard /login may have refreshed token already
    if check_token(live=True) and restart_feed:
        logger.info("auth_recovery_token_file_ok")
        restart_feed()
        return True

    from ..ops.token_refresh import refresh_token_if_needed

    if await refresh_token_if_needed(force=True):
        if restart_feed:
            restart_feed()
        return True

    user = os.getenv("KITE_USER_ID", "")
    pwd = os.getenv("KITE_PASSWORD", "")
    totp = os.getenv("KITE_TOTP_SECRET", "")
    api_key = os.getenv("KITE_API_KEY", "")
    token_file = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
    if not all([user, pwd, totp, api_key]):
        logger.error("auth_recovery_missing_creds", extra={"has_totp": bool(totp)})
        await send_telegram(f"AUTH FAIL {event.type} — re-login at dashboard /login")
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


async def poll_token_health(publish, interval_sec: float = 300.0) -> None:
    """Probe Kite REST; publish TOKEN_EXPIRED when token stops validating."""
    from ..ops.healthchecks import check_token, token_age_hours

    while True:
        try:
            if not check_token(live=True):
                age = token_age_hours()
                await publish(
                    MarketEvent(
                        type=EventType.TOKEN_EXPIRED,
                        payload={"age_h": age, "reason": "live_check_failed"},
                    )
                )
        except Exception:
            logger.exception("token_health_error")
        await asyncio.sleep(interval_sec)

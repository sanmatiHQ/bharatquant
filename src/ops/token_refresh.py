"""
Proactive Kite token refresh — 07:35 IST weekdays + on invalid token.

Requires KITE_TOTP_SECRET (base32 setup key from Google Authenticator QR backup).
Using GAuth on your phone yesterday does NOT persist — Zerodha API tokens reset daily.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("bharatquant.token_refresh")

_TZ = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
_LAST_ATTEMPT = 0.0
_MIN_RETRY_SEC = 300.0


def _has_headless_creds() -> bool:
    return all(
        [
            os.getenv("KITE_USER_ID"),
            os.getenv("KITE_PASSWORD"),
            os.getenv("KITE_TOTP_SECRET"),
            os.getenv("KITE_API_KEY"),
            os.getenv("KITE_API_SECRET"),
        ]
    )


def in_morning_refresh_window() -> bool:
    """07:30–08:15 IST weekdays — after Zerodha daily token reset."""
    now = datetime.now(_TZ)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 7 * 60 + 30 <= minutes <= 8 * 60 + 15


def should_attempt_refresh(*, token_valid: bool) -> bool:
    global _LAST_ATTEMPT
    if not _has_headless_creds():
        return False
    now = time.time()
    if now - _LAST_ATTEMPT < _MIN_RETRY_SEC:
        return False
    if not token_valid:
        return True
    return in_morning_refresh_window()


async def refresh_token_if_needed(*, force: bool = False) -> bool:
    """Headless login when creds set and token invalid or morning window."""
    from ..ops.healthchecks import check_token

    global _LAST_ATTEMPT
    valid = check_token(live=True)
    if valid and not force and not in_morning_refresh_window():
        return True
    if not force and not should_attempt_refresh(token_valid=valid):
        if not valid and not _has_headless_creds():
            logger.warning(
                "token_refresh_skipped",
                extra={"reason": "KITE_TOTP_SECRET missing — add base32 key from GAuth setup"},
            )
        return valid

    _LAST_ATTEMPT = time.time()
    try:
        from ..auth.kite_totp import headless_login

        await headless_login(
            os.environ["KITE_USER_ID"],
            os.environ["KITE_PASSWORD"],
            os.environ["KITE_TOTP_SECRET"],
            os.environ["KITE_API_KEY"],
            os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json"),
        )
        flag = Path(os.getenv("LOGS_DIR", "logs")) / "engine_restart.flag"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(str(int(time.time())), encoding="utf-8")
        logger.info("token_refresh_ok")
        return True
    except Exception:
        logger.exception("token_refresh_failed")
        return False

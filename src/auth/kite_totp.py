"""
Headless Zerodha login via Playwright + TOTP — for TOKEN_EXPIRED recovery.
Requires: KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_SECRET (base32 setup key), KITE_API_KEY

CLI: python3.11 -m src.auth.kite_totp
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pyotp

from .kite_auth import KITE_LOGIN_BASE, build_login_url, exchange_token

logger = logging.getLogger("bharatquant.kite_totp")


def _totp_code(secret: str) -> str:
    return pyotp.TOTP(secret.replace(" ", "").upper()).now()


def _extract_request_token(url: str) -> str:
    if "request_token=" not in url:
        return ""
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    if q.get("request_token"):
        return q["request_token"][0]
    # Fragment-style fallback
    frag = parsed.fragment or url.split("request_token=", 1)[-1]
    if "request_token=" in frag:
        return parse_qs(frag.replace("#", "")).get("request_token", [""])[0]
    return ""


async def headless_login(
    user_id: str,
    password: str,
    totp_secret: str,
    api_key: str,
    token_file: str,
) -> str:
    """Return access_token after browser login. Raises if creds missing."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "playwright not installed — pip install playwright && playwright install chromium"
        ) from e

    login_url = build_login_url(api_key)
    totp = _totp_code(totp_secret)
    redirect_url = os.getenv("KITE_REDIRECT_URL", "http://127.0.0.1:8080/kite/callback")
    request_token = ""

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)

        await page.fill("#userid, input[type='text']", user_id, timeout=15000)
        await page.fill("#password, input[type='password']", password, timeout=15000)
        await page.click("button[type='submit']", timeout=15000)
        await page.wait_for_timeout(2000)

        totp_input = page.locator("#totp, input[type='number'], input[autocomplete='one-time-code']")
        if await totp_input.count():
            await totp_input.first.fill(totp)
            await page.click("button[type='submit']", timeout=15000)
            await page.wait_for_timeout(2000)

        # Wait for redirect carrying request_token (up to 90s)
        for _ in range(90):
            request_token = _extract_request_token(page.url)
            if request_token:
                break
            try:
                await page.wait_for_url(f"**request_token=**", timeout=1000)
            except Exception:
                pass
            request_token = _extract_request_token(page.url)
            if request_token:
                break

        await browser.close()

    if not request_token:
        raise RuntimeError(
            f"TOTP login did not yield request_token — check creds/TOTP secret; last redirect={redirect_url}"
        )

    api_secret = os.environ["KITE_API_SECRET"]
    access = exchange_token(api_key, api_secret, request_token)
    path = Path(token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"data": {"access_token": access}, "ts": int(time.time())}),
        encoding="utf-8",
    )
    logger.info("totp_token_saved", extra={"file": str(path)})
    return access


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uid = os.getenv("KITE_USER_ID", "")
    pwd = os.getenv("KITE_PASSWORD", "")
    totp = os.getenv("KITE_TOTP_SECRET", "")
    api_key = os.getenv("KITE_API_KEY", "")
    token_file = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
    if not all([uid, pwd, totp, api_key, os.getenv("KITE_API_SECRET")]):
        raise SystemExit(
            "Set KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_SECRET (base32 setup key), "
            "KITE_API_KEY, KITE_API_SECRET"
        )
    import asyncio

    token = asyncio.run(headless_login(uid, pwd, totp, api_key, token_file))
    print(f"access_token saved ({len(token)} chars)")


if __name__ == "__main__":
    main()

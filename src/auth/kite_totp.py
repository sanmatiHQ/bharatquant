"""
Headless Zerodha login via Playwright + TOTP — for TOKEN_EXPIRED recovery.
Requires: KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_SECRET, KITE_API_KEY

CLI: python3.11 -m src.auth.kite_totp
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pyotp

logger = logging.getLogger("bharatquant.kite_totp")


def _totp_code(secret: str) -> str:
    return pyotp.TOTP(secret.replace(" ", "")).now()


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
        raise RuntimeError("playwright not installed — pip install playwright && playwright install chromium") from e

    login_url = f"https://kite.zerodha.com/?v=3&api_key={api_key}"
    totp = _totp_code(totp_secret)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(login_url, wait_until="networkidle")
        await page.fill('input[type="text"], input#userid', user_id)
        await page.fill('input[type="password"]', password)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(1500)
        totp_input = page.locator('input[type="number"], input#totp')
        if await totp_input.count():
            await totp_input.fill(totp)
            await page.click('button[type="submit"]')
        await page.wait_for_timeout(3000)
        # Kite redirects with request_token in URL fragment/query
        url = page.url
        request_token = ""
        if "request_token=" in url:
            from urllib.parse import parse_qs, urlparse

            q = urlparse(url).query
            request_token = parse_qs(q).get("request_token", [""])[0]
        await browser.close()

    if not request_token:
        raise RuntimeError("TOTP login did not yield request_token — check creds / selectors")

    from .kite_auth import exchange_token

    api_secret = os.environ["KITE_API_SECRET"]
    access = exchange_token(api_key, api_secret, request_token)
    path = Path(token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"data": {"access_token": access}, "ts": int(time.time())}), encoding="utf-8")
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
            "Set KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_SECRET, KITE_API_KEY, KITE_API_SECRET"
        )
    import asyncio

    token = asyncio.run(headless_login(uid, pwd, totp, api_key, token_file))
    print(f"access_token saved ({len(token)} chars)")


if __name__ == "__main__":
    main()

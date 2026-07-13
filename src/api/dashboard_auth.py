"""Dashboard admin auth — single owner login; public GET is read-only."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

from fastapi import HTTPException, Request, Response

COOKIE_NAME = "bq_admin"
SESSION_MAX_AGE_SEC = 7 * 86400


def _session_secret() -> str:
    secret = os.getenv("DASHBOARD_SESSION_SECRET", "")
    if not secret:
        secret = os.getenv("DASHBOARD_ADMIN_PASSWORD", "changeme")
    return secret


def admin_credentials() -> tuple[str, str]:
    user = os.getenv("DASHBOARD_ADMIN_USER", "admin")
    password = os.getenv("DASHBOARD_ADMIN_PASSWORD", "")
    return user, password


def credentials_configured() -> bool:
    _, password = admin_credentials()
    return bool(password)


def _sign(payload: str) -> str:
    return hmac.new(_session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_token(username: str) -> str:
    ts = str(int(time.time()))
    payload = f"{username}:{ts}"
    return f"{payload}:{_sign(payload)}"


def verify_session_token(token: Optional[str]) -> bool:
    if not token or ":" not in token:
        return False
    try:
        username, ts, sig = token.rsplit(":", 2)
        payload = f"{username}:{ts}"
        if not hmac.compare_digest(_sign(payload), sig):
            return False
        age = int(time.time()) - int(ts)
        return 0 <= age <= SESSION_MAX_AGE_SEC
    except (ValueError, TypeError):
        return False


def authenticate(username: str, password: str) -> bool:
    expected_user, expected_pass = admin_credentials()
    if not expected_pass:
        return False
    return (
        secrets.compare_digest(username, expected_user)
        and secrets.compare_digest(password, expected_pass)
    )


def set_admin_cookie(response: Response, username: str) -> None:
    token = create_session_token(username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE_SEC,
        path="/",
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


def is_admin_request(request: Request) -> bool:
    return verify_session_token(request.cookies.get(COOKIE_NAME))


def require_admin(request: Request) -> None:
    if not is_admin_request(request):
        raise HTTPException(status_code=401, detail="admin login required")


def session_info(request: Request) -> dict:
    authed = is_admin_request(request)
    user, _ = admin_credentials()
    return {
        "authenticated": authed,
        "admin_configured": credentials_configured(),
        "username": user if authed else None,
    }

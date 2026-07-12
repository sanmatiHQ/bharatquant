"""
Zerodha login automation: request_token -> access_token exchange via local callback server.
CLI: python -m src.auth.kite_auth --auto
"""
from __future__ import annotations
import argparse
import hashlib
import http.server
import json
import os
import socketserver
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Optional

import requests

from ..utils.logging_setup import get_logger
from ..utils.backoff import retry


@dataclass
class KiteConfig:
    api_key: str
    api_secret: str
    redirect_url: str
    token_file: str
    logs_dir: str


LOGGER = get_logger("kite_auth", logs_dir=os.getenv("LOGS_DIR", "logs"))

# Browser login lives on kite.zerodha.com — api.kite.trade is REST-only (JSON errors in browser).
KITE_LOGIN_BASE = "https://kite.zerodha.com/connect/login"


def build_login_url(api_key: str) -> str:
    return f"{KITE_LOGIN_BASE}?v=3&api_key={api_key}"


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    request_token: Optional[str] = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "request_token" in params:
            CallbackHandler.request_token = params["request_token"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Token captured. You may close this tab.")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return  # silence default HTTP server logs


@retry()
def exchange_token(api_key: str, api_secret: str, request_token: str) -> str:
    checksum = hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()
    data = {
        "api_key": api_key,
        "request_token": request_token,
        "checksum": checksum,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post("https://api.kite.trade/session/token", data=data, headers=headers, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    return payload["data"]["access_token"]


def run_callback_server(redirect_url: str) -> tuple[str, threading.Thread, int]:
    parsed = urllib.parse.urlparse(redirect_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8080

    httpd = socketserver.TCPServer((host, port), CallbackHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return parsed.geturl(), thread, port


def login_and_exchange(cfg: KiteConfig) -> None:
    redirect, thread, port = run_callback_server(cfg.redirect_url)
    login_url = build_login_url(cfg.api_key)
    LOGGER.info("opening_login", extra={"url": login_url, "redirect": redirect})
    print(f"Open this URL if the browser did not launch:\n{login_url}\n")
    print(f"Waiting for callback at {redirect} (up to 5 min)...")
    webbrowser.open(login_url)

    # Poll for token
    for _ in range(600):  # up to ~5 minutes
        if CallbackHandler.request_token:
            break
        threading.Event().wait(0.5)

    if not CallbackHandler.request_token:
        raise TimeoutError("No request_token received via callback.")

    access_token = exchange_token(cfg.api_key, cfg.api_secret, CallbackHandler.request_token)
    os.makedirs(os.path.dirname(cfg.token_file) or ".", exist_ok=True)
    with open(cfg.token_file, "w", encoding="utf-8") as f:
        json.dump({"data": {"access_token": access_token}}, f)
    LOGGER.info("token_persisted", extra={"file": cfg.token_file})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()

    api_key = os.getenv("KITE_API_KEY")
    api_secret = os.getenv("KITE_API_SECRET")
    redirect_url = os.getenv("KITE_REDIRECT_URL", "http://localhost:8080/kite/callback")
    token_file = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
    logs_dir = os.getenv("LOGS_DIR", "logs")

    if not api_key or not api_secret:
        raise RuntimeError("KITE_API_KEY and KITE_API_SECRET must be set in environment.")

    cfg = KiteConfig(api_key=api_key, api_secret=api_secret, redirect_url=redirect_url, token_file=token_file, logs_dir=logs_dir)

    if args.auto:
        login_and_exchange(cfg)
    else:
        print("Use --auto to start the login flow.")


if __name__ == "__main__":
    main()

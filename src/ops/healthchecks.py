"""
Healthcheck utilities: token, DB, endpoints.
"""
from __future__ import annotations
import os
import json
import sqlite3
import requests


def check_token() -> bool:
    path = os.getenv('KITE_ACCESS_TOKEN_FILE', '.kite_token.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return bool(data.get('access_token'))
    except FileNotFoundError:
        return False


def check_db() -> bool:
    path = os.getenv('SQLITE_PATH', 'data/trading.db')
    try:
        con = sqlite3.connect(path)
        con.execute('SELECT 1')
        con.close()
        return True
    except Exception:
        return False


def check_endpoints() -> dict:
    base = 'http://localhost:8080/api'
    results = {}
    for ep in ['overview', 'positions', 'trades', 'screening', 'market-updates', 'stock-search?q=INFY', 'logs']:
        try:
            r = requests.get(f"{base}/{ep}", timeout=2)
            results[ep] = r.status_code
        except Exception:
            results[ep] = None
    return results

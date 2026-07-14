"""Tests for Kite token hot-reload watcher."""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.ops.healthchecks import check_token_fast, invalidate_token_cache


def test_invalidate_token_cache_clears_fast_path(tmp_path, monkeypatch):
    token_file = tmp_path / ".kite_token.json"
    token_file.write_text(json.dumps({"data": {"access_token": "abc"}}))
    monkeypatch.setenv("KITE_ACCESS_TOKEN_FILE", str(token_file))
    invalidate_token_cache()
    # Fast path reads file directly — still True if file has token
    assert check_token_fast() is True

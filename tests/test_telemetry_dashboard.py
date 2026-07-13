"""Telemetry, slumber, XAI dashboard backend tests."""
from __future__ import annotations

import json
import time

import pytest

from src.db.database import DB, DBConfig
from src.intelligence.xai_reasoner import build_xai_narrative
from src.ops.agent_state import persist_decision, persist_context
from src.ops.slumber_mode import enter_slumber, is_slumbering, slumber_status
from src.ops.system_telemetry import build_system_telemetry


class _Ctx:
    regime = "RISK_ON"
    llm_bias = 0.55
    fii_net_cr = 120.0
    gift_nifty_change_pct = 0.6
    india_vix = 15.0


def test_slumber_blocks_entries(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "sl.db")))
    assert is_slumbering(db) is False
    enter_slumber(db, minutes=30)
    assert is_slumbering(db) is True
    assert slumber_status(db)["remaining_sec"] > 0


def test_xai_narrative_from_decision(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "xai.db")))
    persist_context(db, _Ctx())
    persist_decision(db, {
        "action": "BUY",
        "symbol": "NIFTYBEES",
        "strategy": "fast_snapshot",
        "signal": "BUY",
        "reason": "momentum breakout",
    })
    xai = build_xai_narrative(db, {"llm_bias": 0.55, "fii_net_cr": 120, "gift_nifty_change_pct": 0.6, "india_vix": 15, "regime": "RISK_ON"})
    assert "BUY" in xai["narrative"]
    assert "NIFTYBEES" in xai["narrative"]


def test_telemetry_shape(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "tel.db")))
    persist_context(db, _Ctx())
    t = build_system_telemetry(db, ws_live=True, engine_live=True)
    assert "kite_status_ring" in t
    assert "cpu_pct" in t or t["cpu_pct"] is None
    assert t["db_ok"] is True


def test_dashboard_feed_includes_telemetry(tmp_path):
    db = DB(DBConfig(sqlite_path=str(tmp_path / "feed.db")))
    persist_context(db, _Ctx())
    from src.api.dashboard_feed import build_live_feed

    feed = build_live_feed(db)
    assert "telemetry" in feed
    assert "xai" in feed
    assert "sparklines" in feed

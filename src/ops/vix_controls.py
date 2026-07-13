"""VIX-aware sizing, stop-loss, and budget safety gates."""
from __future__ import annotations

import json
import os

from ..db.database import DB


def vix_from_db(db: DB) -> float:
    row = db._conn.execute("SELECT v FROM settings WHERE k='agent_context'").fetchone()
    if not row:
        return 0.0
    try:
        return float(json.loads(row["v"]).get("india_vix", 0) or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def vix_safe_for_budget(vix: float) -> bool:
    ceiling = float(os.getenv("VIX_BUDGET_AUTO_APPROVE_MAX", "22"))
    floor = float(os.getenv("VIX_BUDGET_AUTO_APPROVE_MIN", "0"))
    if vix <= 0:
        return True
    return floor <= vix <= ceiling


def vix_sizing_scale(vix: float) -> float:
    """High vol → smaller first-trade sizing."""
    if vix <= 0 or vix <= float(os.getenv("VIX_SIZING_NEUTRAL", "15")):
        return 1.0
    if vix <= 20:
        return float(os.getenv("VIX_SIZING_SCALE_20", "0.75"))
    if vix <= 25:
        return float(os.getenv("VIX_SIZING_SCALE_25", "0.5"))
    return float(os.getenv("VIX_SIZING_SCALE_HIGH", "0.35"))


def vix_adjusted_stop_pct(base_pct: float, vix: float) -> float:
    """Higher VIX → tighter stop-loss."""
    if vix <= 0 or vix <= float(os.getenv("VIX_STOP_NEUTRAL", "14")):
        return base_pct
    if vix <= 18:
        return base_pct * float(os.getenv("VIX_STOP_SCALE_18", "0.9"))
    if vix <= 22:
        return base_pct * float(os.getenv("VIX_STOP_SCALE_22", "0.75"))
    return base_pct * float(os.getenv("VIX_STOP_SCALE_HIGH", "0.6"))


def llm_bearish_veto_threshold() -> float:
    return float(os.getenv("LLM_BEARISH_VETO", "-0.5"))

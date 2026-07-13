"""Agent Sandbox Review — shadow backtest + historical session replay summary."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from ..db.database import DB
from ..rl.shadow_backtest import compare_policies

_TZ = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
_CACHE_KEY = "sandbox_review_cache"


def _setting(db: DB, key: str) -> dict | None:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["v"])
    except json.JSONDecodeError:
        return {"raw": row["v"]}


def build_sandbox_review(db: DB, *, recompute: bool = False) -> dict:
    """Dashboard sandbox tab — uses post-market shadow cache; optional live recompute."""
    version = os.getenv("RL_ACTIVE_VERSION", "ppo_v1")
    model_dir = Path(os.getenv("RL_MODEL_DIR", "models/rl")) / version
    stable = model_dir / "policy_stable.npz"
    live = model_dir / "policy.npz"

    rl_meta = _setting(db, "rl_last_train_meta") or {}
    slippage = _setting(db, "slippage_summary_latest")

    cached = _setting(db, _CACHE_KEY)
    if cached and not recompute and cached.get("rl_version") == version:
        cached["from_cache"] = True
        return cached

    comparison = rl_meta.get("shadow")
    if recompute and stable.exists() and live.exists():
        comparison = compare_policies(db, stable, live)

    stable_eval = comparison.get("stable") if comparison else None
    candidate_eval = comparison.get("candidate") if comparison else None

    rows = db._conn.execute(
        """
        SELECT date(ts, 'unixepoch', 'localtime') AS day,
               MIN(total_value) AS low,
               MAX(total_value) AS high,
               COUNT(*) AS snaps
        FROM portfolio_history
        GROUP BY day
        ORDER BY day DESC
        LIMIT 10
        """
    ).fetchall()
    history_days = [dict(r) for r in rows]

    promote_recommendation = "hold_stable"
    if comparison:
        promote_recommendation = "use_candidate" if comparison.get("passed") else "hold_stable"
    elif rl_meta.get("promoted"):
        promote_recommendation = "use_candidate"

    payload = {
        "ts": int(time.time()),
        "rl_version": version,
        "promote_recommendation": promote_recommendation,
        "shadow_comparison": comparison,
        "rl_last_train": rl_meta,
        "slippage_latest": slippage,
        "stable_eval": stable_eval,
        "candidate_eval": candidate_eval,
        "history_days": history_days,
        "lookback_days": int(os.getenv("RL_SHADOW_LOOKBACK_DAYS", "30")),
        "from_cache": False,
        "note": (
            "Shadow scores refresh at 16:15 post-market (or per-trade RL). "
            "Pass ?recompute=1 to force live bar replay."
        ),
    }

    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (_CACHE_KEY, json.dumps(payload)),
        )
    return payload

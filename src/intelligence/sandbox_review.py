"""Agent Sandbox Review — shadow backtest + historical session replay summary."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..db.database import DB
from ..rl.shadow_backtest import compare_policies, evaluate_policy_on_bars

_TZ = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))


def _setting(db: DB, key: str) -> dict | None:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["v"])
    except json.JSONDecodeError:
        return {"raw": row["v"]}


def build_sandbox_review(db: DB) -> dict:
    """Dashboard sandbox tab — RL shadow gate + optional date replay metrics."""
    version = os.getenv("RL_ACTIVE_VERSION", "ppo_v1")
    model_dir = Path(os.getenv("RL_MODEL_DIR", "models/rl")) / version
    stable = model_dir / "policy_stable.npz"
    live = model_dir / "policy.npz"

    comparison = None
    stable_eval = None
    candidate_eval = None
    if stable.exists() and live.exists():
        comparison = compare_policies(db, stable, live)
        stable_eval = comparison.get("stable")
        candidate_eval = comparison.get("candidate")
    elif stable.exists():
        stable_eval = evaluate_policy_on_bars(db, stable)
    elif live.exists():
        candidate_eval = evaluate_policy_on_bars(db, live)

    rl_meta = _setting(db, "rl_last_train_meta")
    slippage = _setting(db, "slippage_summary_latest")

    # Last 10 session days from portfolio_history (daily close snapshots)
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

    return {
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
        "note": (
            "Candidate promoted only if shadow score within tolerance vs stable. "
            "Use history_days to pick dates for manual GCS bar replay."
        ),
    }

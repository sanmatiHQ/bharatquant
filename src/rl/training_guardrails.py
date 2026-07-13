"""RL training guardrails — low LR, abnormal-day dampening, shadow promotion gate."""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..db.database import DB
from .ppo_trainer import PPOConfig, train_ppo
from .shadow_backtest import compare_policies

logger = logging.getLogger("bharatquant.training_guardrails")

_TZ = ZoneInfo(os.getenv("TZ", "Asia/Kolkata"))
STABLE_SUFFIX = "policy_stable.npz"
KEY_RL_TRAIN_DAY = "rl_train_day"


def already_trained_today(db: DB) -> bool:
    return get_setting(db, KEY_RL_TRAIN_DAY) == datetime.now(_TZ).strftime("%Y-%m-%d")


def _mark_trained_today(db: DB) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (KEY_RL_TRAIN_DAY, datetime.now(_TZ).strftime("%Y-%m-%d")),
        )


def get_setting(db: DB, key: str) -> str | None:
    row = db._conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    return str(row["v"]) if row else None


def _today_start_ts() -> int:
    now = datetime.now(_TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def detect_abnormal_day(db: DB) -> tuple[bool, str, float]:
    """
    Flag flash-crash / budget-day style outliers so we dampen single-day learning.
    """
    threshold = float(os.getenv("RL_ABNORMAL_DAY_PCT", "3.0"))
    row = db._conn.execute(
        """
        SELECT total_value FROM portfolio_history
        WHERE ts >= ? ORDER BY ts ASC LIMIT 1
        """,
        (_today_start_ts(),),
    ).fetchone()
    end = db._conn.execute(
        "SELECT total_value FROM portfolio_history ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    if row and end and float(row["total_value"]) > 0:
        move = abs(float(end["total_value"]) - float(row["total_value"])) / float(row["total_value"]) * 100
        if move >= threshold:
            return True, "portfolio_move", move
    gift = db._conn.execute(
        "SELECT payload_json FROM ingest_log WHERE event_type='GIFT_TICK' ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    if gift:
        try:
            pct = abs(float(json.loads(gift["payload_json"]).get("change_pct", 0)))
            if pct >= threshold:
                return True, "gift_gap", pct
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return False, "normal", 0.0


def training_config(db: DB, abnormal: bool) -> PPOConfig:
    base_lr = float(os.getenv("RL_LEARNING_RATE", "1e-5"))
    epochs = int(os.getenv("RL_TRAIN_EPOCHS", "2" if not abnormal else "1"))
    if abnormal:
        base_lr *= float(os.getenv("RL_ABNORMAL_LR_SCALE", "0.3"))
        epochs = max(1, epochs // 2)
    return PPOConfig(lr=base_lr, epochs=epochs)


def sb3_timesteps(abnormal: bool) -> int:
    base = int(os.getenv("RL_SB3_TIMESTEPS", "2000"))
    if abnormal:
        return max(256, int(base * float(os.getenv("RL_ABNORMAL_TIMESTEPS_SCALE", "0.25"))))
    return base


def snapshot_stable_policy(model_dir: str, version: str) -> Path:
    d = Path(model_dir) / version
    d.mkdir(parents=True, exist_ok=True)
    live = d / "policy.npz"
    stable = d / STABLE_SUFFIX
    if live.exists():
        shutil.copy2(live, stable)
        logger.info("rl_stable_snapshot", extra={"path": str(stable)})
    return stable


def revert_to_stable(model_dir: str, version: str) -> bool:
    d = Path(model_dir) / version
    stable = d / STABLE_SUFFIX
    live = d / "policy.npz"
    if not stable.exists():
        return False
    shutil.copy2(stable, live)
    logger.warning("rl_reverted_to_stable", extra={"version": version})
    return True


def _persist_train_meta(db: DB, meta: dict) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("rl_last_train_meta", json.dumps(meta)),
        )


def guarded_train_and_promote(
    db: DB, model_dir: str, version: str, *, skip_shadow: bool = False
) -> dict:
    """
    1. Snapshot yesterday's stable weights
    2. Train with low LR (dampened if abnormal day)
    3. Shadow backtest 30d 5m bars — revert if candidate regresses
    """
    abnormal, ab_reason, ab_mag = detect_abnormal_day(db)
    stable_path = snapshot_stable_policy(model_dir, version)
    if not stable_path.exists():
        # First run — stable = current before train
        live = Path(model_dir) / version / "policy.npz"
        if live.exists():
            shutil.copy2(live, stable_path)

    cfg = training_config(db, abnormal)
    use_sb3 = os.getenv("RL_USE_SB3", "true").lower() in ("1", "true", "yes")

    if use_sb3:
        from .sb3_trainer import SB3_AVAILABLE, train_sb3

        if SB3_AVAILABLE:
            try:
                train_result = train_sb3(
                    db, model_dir, version, timesteps=sb3_timesteps(abnormal)
                )
            except Exception as exc:
                logger.warning("sb3_train_failed_fallback_numpy", extra={"error": str(exc)})
                train_result = train_ppo(db, model_dir, version, cfg=cfg)
        else:
            train_result = train_ppo(db, model_dir, version, cfg=cfg)
    else:
        train_result = train_ppo(db, model_dir, version, cfg=cfg)

    if train_result.get("status") != "ok":
        meta = {"promoted": False, "reason": "train_skipped", "train": train_result}
        _persist_train_meta(db, meta)
        return meta

    live_path = Path(model_dir) / version / "policy.npz"
    if skip_shadow or not stable_path.exists():
        promoted = True
        comparison = {"passed": True, "reason": "skip_shadow" if skip_shadow else "first_train"}
        if live_path.exists():
            shutil.copy2(live_path, stable_path)
    else:
        comparison = compare_policies(db, stable_path, live_path)
        promoted = comparison["passed"]
        if not promoted:
            revert_to_stable(model_dir, version)
        else:
            shutil.copy2(live_path, stable_path)

    meta = {
        "ts": int(time.time()),
        "promoted": promoted,
        "abnormal_day": abnormal,
        "abnormal_reason": ab_reason,
        "abnormal_magnitude": ab_mag,
        "learning_rate": cfg.lr,
        "epochs": cfg.epochs,
        "train": train_result,
        "shadow": comparison,
    }
    _persist_train_meta(db, meta)
    _mark_trained_today(db)
    logger.info("rl_guarded_train_done", extra={"promoted": promoted, "abnormal": abnormal})
    return meta


REGIME_BUCKETS = ("BULL", "BEAR", "SIDEWAYS", "HIGH_VOL")
_REGIME_STATE_IDX = 2


def _regime_bucket_from_state(state: list | dict) -> str:
    if isinstance(state, dict):
        vec = [float(state.get(str(i), 0)) for i in range(16)]
    else:
        vec = list(state)
    if len(vec) <= _REGIME_STATE_IDX:
        return "SIDEWAYS"
    r = float(vec[_REGIME_STATE_IDX])
    if r >= 0.5:
        return "BULL"
    if r <= -0.5:
        return "BEAR"
    if abs(r) < 0.15:
        return "SIDEWAYS"
    return "HIGH_VOL"


def _load_regime_transitions(db: DB, bucket: str, limit: int = 400) -> list[dict]:
    import json

    import numpy as np

    from .state_encoder import STATE_DIM, action_index

    cap = limit
    cur = db._conn.execute(
        """
        SELECT state, action, reward, next_state, done
        FROM rl_transitions ORDER BY ts DESC LIMIT ?
        """,
        (cap * 4,),
    )
    rows = []
    for r in cur.fetchall():
        try:
            state = json.loads(r["state"].decode() if isinstance(r["state"], bytes) else r["state"])
            nxt = json.loads(r["next_state"].decode() if isinstance(r["next_state"], bytes) else r["next_state"])
            if isinstance(state, dict):
                state = list(state.values())[:STATE_DIM]
            if isinstance(nxt, dict):
                nxt = list(nxt.values())[:STATE_DIM]
            if _regime_bucket_from_state(state) != bucket:
                continue
            rows.append({
                "state": np.array(state, dtype=np.float64),
                "action": action_index(str(r["action"])),
                "reward": float(r["reward"]),
                "next_state": np.array(nxt, dtype=np.float64),
                "done": bool(r["done"]),
            })
            if len(rows) >= cap:
                break
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return rows


def _fine_tune_policy(policy: "PPOPolicy", rows: list, cfg: PPOConfig) -> None:
    import numpy as np

    states = np.stack([r["state"] for r in rows])
    actions = np.array([r["action"] for r in rows])
    rewards = np.array([r["reward"] for r in rows])
    dones = np.array([r["done"] for r in rows])
    returns = np.zeros_like(rewards)
    g = 0.0
    for i in reversed(range(len(rewards))):
        g = rewards[i] + cfg.gamma * g * (1.0 - dones[i])
        returns[i] = g
    adv = returns - np.array([policy.value(s) for s in states])
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    for _ in range(max(1, cfg.epochs)):
        for i in range(len(rows)):
            s = states[i]
            a = actions[i]
            old_p = policy.probs(s)[a]
            adv_i = adv[i]
            logits = s @ policy.W + policy.b
            logits -= logits.max()
            probs = np.exp(logits) / np.exp(logits).sum()
            new_p = probs[a]
            ratio = new_p / max(old_p, 1e-8)
            clipped = np.clip(ratio, 1 - cfg.clip_eps, 1 + cfg.clip_eps)
            loss_pg = -min(ratio * adv_i, clipped * adv_i)
            for j in range(probs.shape[0]):
                grad = probs[j] * (1 if j == a else 0) - probs[j] * probs[a]
                policy.W[:, j] -= cfg.lr * loss_pg * grad * s
                policy.b[j] -= cfg.lr * loss_pg * grad
            v_err = policy.value(s) - returns[i]
            policy.Vw -= cfg.lr * v_err * s
            policy.Vb -= cfg.lr * v_err


def train_regime_policies(db: DB, model_dir: str, base_version: str = "ppo_v1") -> dict:
    """
    Bootstrap + fine-tune per-regime policies under models/rl/regimes/{BUCKET}/policy.npz.
    Falls back to base ppo_v1 weights when regime-specific transitions are sparse.
    """
    from .ppo_trainer import PPOPolicy

    base_path = Path(model_dir) / base_version / "policy.npz"
    if not base_path.exists():
        return {"status": "skipped", "reason": "no_base_policy", "path": str(base_path)}

    cfg = training_config(db, abnormal=False)
    regimes_out: dict[str, dict] = {}
    for bucket in REGIME_BUCKETS:
        dest = Path(model_dir) / "regimes" / bucket / "policy.npz"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_path, dest)
        rows = _load_regime_transitions(db, bucket)
        trained = False
        if len(rows) >= 8:
            pol = PPOPolicy.load(dest)
            _fine_tune_policy(pol, rows, cfg)
            pol.save(dest)
            trained = True
        regimes_out[bucket] = {
            "path": str(dest),
            "transitions": len(rows),
            "fine_tuned": trained,
        }
        logger.info("regime_policy_ready", extra={"bucket": bucket, "n": len(rows), "trained": trained})

    meta = {"ts": int(time.time()), "status": "ok", "base": str(base_path), "regimes": regimes_out}
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("rl_regime_policies_meta", json.dumps(meta)),
        )
    return meta

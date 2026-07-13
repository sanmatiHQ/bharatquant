"""
Offline PPO trainer CLI — learns from rl_transitions, syncs to GCS.

  python3.11 -m src.rl.rl_trainer --version ppo_v1 --epochs 4
  python3.11 -m src.rl.rl_trainer --version ppo_v1 --sync-gcs
"""
from __future__ import annotations

import argparse
import logging
import os

from dotenv import load_dotenv

from ..db.database import DB, DBConfig
from ..ops.gcs_store import restore_rl_model, sync_rl_model
from .ppo_trainer import PPOConfig, train_ppo
from .training_guardrails import guarded_train_and_promote, train_regime_policies

load_dotenv()
logger = logging.getLogger("bharatquant.rl_trainer")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Train PPO policy from rl_transitions")
    parser.add_argument("--version", default=os.getenv("RL_ACTIVE_VERSION", "ppo_v1"))
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--sync-gcs", action="store_true", help="Upload policy to GCS after train")
    parser.add_argument("--restore-gcs", action="store_true", help="Download policy from GCS before train")
    parser.add_argument("--train-regimes", action="store_true", help="Bootstrap/fine-tune regime policy.npz files")
    parser.add_argument("--force-postmarket", action="store_true", help="Run post-market train+regimes+sandbox (ignore day gate)")
    args = parser.parse_args()

    sqlite_path = os.getenv("SQLITE_PATH", "data/trading.db")
    model_dir = os.getenv("RL_MODEL_DIR", "models/rl")
    db = DB(DBConfig(sqlite_path=sqlite_path))

    if args.force_postmarket:
        import asyncio
        from ..ops.market_routines import run_postmarket_routine

        result = asyncio.run(run_postmarket_routine(db, force=True))
        print(result)
        return

    if args.restore_gcs:
        ok = restore_rl_model(model_dir, args.version)
        print(f"restore_gcs: {'ok' if ok else 'skipped/failed'}")

    if args.train_regimes and not args.sync_gcs:
        regime_result = train_regime_policies(db, model_dir, args.version)
        print(regime_result)
        return

    use_guarded = os.getenv("RL_USE_GUARDRAILS", "true").lower() in ("1", "true", "yes")
    if use_guarded:
        result = guarded_train_and_promote(db, model_dir, args.version)
    else:
        result = train_ppo(
            db,
            model_dir,
            version=args.version,
            cfg=PPOConfig(epochs=args.epochs, batch_size=args.batch_size),
        )
    print(result)

    if args.train_regimes:
        regime_result = train_regime_policies(db, model_dir, args.version)
        print(regime_result)

    if args.sync_gcs and (result.get("status") == "ok" or result.get("promoted")):
        ok = sync_rl_model(model_dir, args.version)
        print(f"sync_gcs: {'ok' if ok else 'failed'}")


if __name__ == "__main__":
    main()

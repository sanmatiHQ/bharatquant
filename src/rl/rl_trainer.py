"""
Offline trainer stub for PPO learning (no-op today).
CLI: python -m src.rl.rl_trainer --version ppo_v1 --epochs 5
"""
from __future__ import annotations
import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=False, default="ppo_v1")
    parser.add_argument("--epochs", type=int, default=5)
    args = parser.parse_args()
    print(f"RL trainer stub: version={args.version}, epochs={args.epochs}")


if __name__ == "__main__":
    main()

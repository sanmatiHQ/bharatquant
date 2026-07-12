"""
Versioned RL agent interface with baseline and PPO stubs.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RLAgent:
    model_dir: str
    active_version: str

    def load(self, version: str) -> None:
        self.active_version = version

    def is_learning_enabled(self) -> bool:
        return False

    def act(self, state: dict, symbol: str) -> str:
        if self.active_version == "baseline":
            # deterministic baseline: act based on provided score
            score = float(state.get("score", 0.0))
            return "buy" if score > 0 else "hold"
        # ppo_v1 stub
        return "hold"

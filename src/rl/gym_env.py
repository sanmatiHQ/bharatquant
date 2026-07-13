"""
OpenAI Gymnasium NSE trading environment — daily ₹2k budget reset, action masking.
"""
from __future__ import annotations

import os
from typing import Any, Optional, Tuple

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces

    GYM_AVAILABLE = True
except ImportError:
    GYM_AVAILABLE = False
    gym = object  # type: ignore
    spaces = None  # type: ignore

from ..rl.state_encoder import STATE_DIM, encode_state_from_dict
from ..rl.action_mask import apply_action_mask, is_buy_allowed, max_intraday_drawdown_pct


if GYM_AVAILABLE:

    class NSETradingEnv(gym.Env):
        """Custom Gymnasium env for paper RL training."""

        metadata = {"render_modes": []}

        def __init__(
            self,
            price_series: np.ndarray,
            *,
            daily_budget: float = 2000.0,
            starting_cash: float = 10000.0,
            max_steps: int = 390,
        ) -> None:
            super().__init__()
            self.prices = price_series.astype(np.float64)
            self.daily_budget = daily_budget
            self.starting_cash = starting_cash
            self.max_steps = min(max_steps, len(price_series) - 1)
            self.action_space = spaces.Discrete(3)
            self.observation_space = spaces.Box(low=-1.0, high=1.0, shape=(STATE_DIM,), dtype=np.float32)
            self._step = 0
            self._day_spent = 0.0
            self._cash = starting_cash
            self._qty = 0
            self._avg = 0.0
            self._hold_minutes = 0.0
            self._peak_equity = starting_cash
            self._ctx: dict = {}

        def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None) -> Tuple[np.ndarray, dict]:
            super().reset(seed=seed)
            self._step = 0
            self._day_spent = 0.0
            self._cash = self.starting_cash
            self._qty = 0
            self._avg = 0.0
            self._hold_minutes = 0.0
            self._peak_equity = self.starting_cash
            self._ctx = {
                "fii_net_cr": 0.0,
                "gift_nifty_change_pct": 0.0,
                "india_vix": 15.0,
                "llm_bias": 0.0,
                "spread_bps": 5.0,
                "futures_oi_chg": 0.0,
                "us_vix_chg": 0.0,
                "regime": "NEUTRAL",
            }
            return self._obs(), {}

        def _price(self) -> float:
            idx = min(self._step, len(self.prices) - 1)
            return float(self.prices[idx])

        def _obs(self) -> np.ndarray:
            rem = max(0.0, self.daily_budget - self._day_spent)
            return np.array(
                encode_state_from_dict(
                    self._ctx,
                    score=0.5,
                    confidence=0.5,
                    pos_frac=min(1.0, self._qty / 5.0),
                    budget_remaining_frac=rem / self.daily_budget if self.daily_budget > 0 else 0.0,
                    hold_minutes=self._hold_minutes,
                ),
                dtype=np.float32,
            )

        def _equity(self, ltp: float) -> float:
            return self._cash + self._qty * ltp

        def _drawdown_halted(self, ltp: float) -> bool:
            eq = self._equity(ltp)
            self._peak_equity = max(self._peak_equity, eq)
            if self._peak_equity <= 0:
                return False
            dd = (self._peak_equity - eq) / self._peak_equity * 100.0
            return dd >= max_intraday_drawdown_pct()

        def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, dict]:
            ltp = self._price()
            reward = 0.0
            terminated = False
            truncated = False
            halted = self._drawdown_halted(ltp)

            action = apply_action_mask(
                action,
                cash=self._cash,
                ltp=ltp,
                db=None,
                has_position=self._qty > 0,
                drawdown_halted=halted,
            )

            if action == 1 and not is_buy_allowed(self._cash, ltp, db=None):
                action = 0
                reward -= 0.001
            if action == 1 and self._day_spent + ltp > self.daily_budget:
                action = 0
                reward -= 0.002
            if action == 2 and self._qty <= 0:
                action = 0

            if action == 1 and self._qty == 0:
                self._qty = 1
                self._avg = ltp
                self._cash -= ltp
                self._day_spent += ltp
                self._hold_minutes = 0.0
            elif action == 2 and self._qty > 0:
                pnl = (ltp - self._avg) * self._qty
                reward += pnl / max(1.0, self._avg * self._qty)
                self._cash += ltp * self._qty
                self._qty = 0
                self._avg = 0.0
                self._hold_minutes = 0.0
            elif halted and self._qty > 0:
                pnl = (ltp - self._avg) * self._qty
                reward += pnl / max(1.0, self._avg * self._qty)
                self._cash += ltp * self._qty
                self._qty = 0
                self._avg = 0.0
                self._hold_minutes = 0.0
                truncated = True
            elif self._qty > 0:
                self._hold_minutes += 1.0
                unreal = (ltp - self._avg) / self._avg * 100.0 if self._avg > 0 else 0.0
                from ..rl.reward import reward_config_from_env, compute_reward

                cfg = reward_config_from_env()
                reward += compute_reward(0.0, 0.0, cfg, hold_minutes=self._hold_minutes, unrealized_pnl_pct=unreal) * 0.01

            self._step += 1
            if self._step >= self.max_steps:
                truncated = True
                if self._qty > 0:
                    pnl = (ltp - self._avg) * self._qty
                    reward += pnl / max(1.0, self._avg * self._qty)

            return self._obs(), float(reward), terminated, truncated, {"ltp": ltp, "qty": self._qty}

else:

    class NSETradingEnv:  # type: ignore
        def __init__(self, *args, **kwargs) -> None:
            raise ImportError("gymnasium required: pip install gymnasium")


def make_env_from_db(db, symbol: str, daily_budget: float | None = None) -> NSETradingEnv:
    sym = symbol.replace("NSE:", "")
    rows = db._conn.execute(
        "SELECT close FROM bar_log WHERE symbol=? AND interval='5m' ORDER BY ts ASC",
        (sym,),
    ).fetchall()
    if len(rows) < 50:
        prices = np.linspace(100, 105, 200)
    else:
        prices = np.array([float(r["close"]) for r in rows], dtype=np.float64)
    budget = daily_budget or float(os.getenv("DAILY_INVESTMENT_MAX", "2000"))
    return NSETradingEnv(prices, daily_budget=budget)

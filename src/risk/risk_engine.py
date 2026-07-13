"""
Risk engine enforcing stop-loss, take-profit, trailing stop, and max positions.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Tuple


@dataclass
class RiskConfig:
    stop_loss_percent: float
    max_daily_loss_percent: float
    max_daily_loss_rupees: float
    max_positions: int
    take_profit_percent: float = 2.0
    trailing_stop_percent: float = 1.5
    max_hold_minutes: int = 240


def risk_config_from_env() -> RiskConfig:
    return RiskConfig(
        stop_loss_percent=float(os.getenv("STOP_LOSS_PCT", "2.5")),
        max_daily_loss_percent=float(os.getenv("MAX_DAILY_LOSS_PCT", "2")),
        max_daily_loss_rupees=float(os.getenv("MAX_DAILY_LOSS_RUPEES", "2000")),
        max_positions=int(os.getenv("MAX_POSITIONS", "8")),
        take_profit_percent=float(os.getenv("TAKE_PROFIT_PCT", "4.0")),
        trailing_stop_percent=float(os.getenv("TRAILING_STOP_PCT", "1.2")),
        max_hold_minutes=int(os.getenv("MAX_HOLD_MINUTES", "240")),
    )


class RiskEngine:
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg

    def can_open_new(self, state: dict) -> tuple[bool, str]:
        """Check portfolio state for new positions gate."""
        if state.get("halted"):
            return False, "kill_switch"
        total_eq = float(state.get("total_equity", 0))
        day_peak = float(state.get("day_peak_equity", total_eq))
        drawdown = 0.0 if day_peak == 0 else (day_peak - total_eq) / day_peak * 100.0
        if drawdown >= self.cfg.max_daily_loss_percent:
            return False, "daily_loss_pct_gate"
        loss_inr = float(state.get("day_loss_rupees", 0))
        if loss_inr >= self.cfg.max_daily_loss_rupees:
            return False, "daily_loss_rupees_gate"
        if int(state.get("open_positions", 0)) >= self.cfg.max_positions:
            return False, "max_positions"
        return True, "ok"

    def should_exit(self, symbol_state: dict, peak_price: float = 0.0, india_vix: float = 0.0) -> Tuple[bool, str]:
        """Exit on stop-loss, take-profit, trailing stop, or max hold time."""
        avg = float(symbol_state.get("avg_price", 0))
        last = float(symbol_state.get("last_price", 0))
        if avg <= 0 or last <= 0:
            return False, ""

        from ..ops.vix_controls import vix_adjusted_stop_pct

        stop_pct = vix_adjusted_stop_pct(self.cfg.stop_loss_percent, india_vix)
        gain = (last - avg) / avg * 100.0
        drop = (avg - last) / avg * 100.0
        if drop >= stop_pct:
            return True, f"stop_loss_{drop:.2f}pct_vix{india_vix:.0f}"

        peak = max(peak_price, float(symbol_state.get("peak_price", last)))
        if peak > avg * 1.008 and last <= avg * 1.001:
            return True, "breakeven_lock"

        if gain >= self.cfg.take_profit_percent:
            return True, f"take_profit_{gain:.2f}pct"

        if peak > avg and peak > 0:
            trail_drop = (peak - last) / peak * 100.0
            trail_arm = float(os.getenv("TRAIL_ARM_GAIN_PCT", "0.6"))
            if gain > trail_arm and trail_drop >= self.cfg.trailing_stop_percent:
                return True, f"trailing_stop_{trail_drop:.2f}pct"

        open_ts = int(symbol_state.get("open_ts", 0))
        if open_ts > 0 and self.cfg.max_hold_minutes > 0:
            held_min = (time.time() - open_ts) / 60.0
            if held_min >= self.cfg.max_hold_minutes:
                return True, f"max_hold_{int(held_min)}min"

        return False, ""

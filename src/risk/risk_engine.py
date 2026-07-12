"""
Risk engine enforcing stop-loss, daily loss gate, and max positions.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple


@dataclass
class RiskConfig:
    stop_loss_percent: float
    max_daily_loss_percent: float
    max_daily_loss_rupees: float
    max_positions: int


class RiskEngine:
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg

    def can_open_new(self, state: dict) -> tuple[bool, str]:
        """Check portfolio state for new positions gate.
        state expects keys: total_equity, day_peak_equity, day_loss_rupees, open_positions
        """
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

    def should_exit(self, symbol_state: dict) -> bool:
        """Signal exit if price has moved below stop-loss threshold from avg price."""
        avg = float(symbol_state.get("avg_price", 0))
        last = float(symbol_state.get("last_price", 0))
        if avg <= 0:
            return False
        drop = (avg - last) / avg * 100.0
        return drop >= self.cfg.stop_loss_percent

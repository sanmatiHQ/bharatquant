"""Per-strategy trade stats for Kelly sizing — re-exports unified strategy_stats."""
from __future__ import annotations

from .strategy_stats import kelly_inputs_for_strategy

__all__ = ["kelly_inputs_for_strategy"]

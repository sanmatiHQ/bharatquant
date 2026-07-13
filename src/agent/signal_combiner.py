"""Net signal arbitration per symbol — prevents buy/sell churn from multi-strategy races."""
from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional

from ..strategies.base import MarketContext, Signal

_ACTION_SIGN = {"BUY": 1.0, "SELL": -1.0, "HEDGE": 0.5, "HOLD": 0.0}


class SignalCombiner:
    """500ms sliding window → one net-direction signal per symbol."""

    def __init__(self, window_ms: int | None = None) -> None:
        self.window_ms = window_ms or int(os.getenv("SIGNAL_COMBINE_WINDOW_MS", "500"))
        self._buffer: Dict[str, list[tuple[float, Signal]]] = defaultdict(list)

    def _prune(self, sym: str, now_ms: float) -> None:
        cutoff = now_ms - self.window_ms
        self._buffer[sym] = [(t, s) for t, s in self._buffer[sym] if t >= cutoff]

    def push(self, signal: Signal, *, ts_ms: float | None = None) -> None:
        sym = signal.symbol.replace("NSE:", "")
        if not sym or signal.action not in _ACTION_SIGN:
            return
        now = ts_ms if ts_ms is not None else time.time() * 1000.0
        self._prune(sym, now)
        self._buffer[sym].append((now, signal))

    def combine(
        self,
        signals: List[Signal],
        ctx: MarketContext,
        weights: Dict[str, float],
        adjust_conf: Callable[[Signal], float],
        *,
        ts_ms: float | None = None,
    ) -> List[Signal]:
        """Collapse competing signals per symbol into a single net objective."""
        now = ts_ms if ts_ms is not None else time.time() * 1000.0
        by_sym: Dict[str, List[Signal]] = defaultdict(list)
        for s in signals:
            sym = s.symbol.replace("NSE:", "")
            if sym:
                by_sym[sym].append(s)
                self.push(s, ts_ms=now)

        out: List[Signal] = []
        threshold = float(os.getenv("SIGNAL_NET_THRESHOLD", "0.18"))
        for sym, sigs in by_sym.items():
            merged: list[Signal] = []
            seen: set[tuple] = set()
            for s in list(sigs) + [x for _, x in self._buffer[sym]]:
                key = (s.strategy_id, s.symbol, s.action, s.reason)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(s)
            net_sig = self._net_for_symbol(sym, merged, ctx, weights, adjust_conf, threshold)
            if net_sig:
                out.append(net_sig)
        return out

    def _net_for_symbol(
        self,
        sym: str,
        signals: List[Signal],
        ctx: MarketContext,
        weights: Dict[str, float],
        adjust_conf: Callable[[Signal], float],
        threshold: float,
    ) -> Optional[Signal]:
        if not signals:
            return None
        if len(signals) == 1:
            return self._position_guard(sym, signals[0], ctx)

        buy_score = 0.0
        sell_score = 0.0
        contributors: list[str] = []
        for s in signals:
            w = float(weights.get(s.strategy_id, 1.0))
            conf = adjust_conf(s)
            sign = _ACTION_SIGN.get(s.action, 0.0)
            if sign > 0:
                buy_score += conf * w * sign
            elif sign < 0:
                sell_score += conf * w * abs(sign)
            contributors.append(s.strategy_id)

        net = buy_score - sell_score
        if abs(net) < threshold:
            return None

        action = "BUY" if net > 0 else "SELL"
        best = max(signals, key=lambda x: x.confidence)
        pos = (ctx.positions or {}).get(sym) or {}
        qty = int(pos.get("qty", 0) or 0)

        if action == "BUY" and qty > 0 and buy_score > 0 and sell_score > threshold * 0.5:
            return None
        if action == "SELL" and qty <= 0:
            return None

        conf = min(0.92, abs(net) / max(buy_score + sell_score, 0.01))
        return Signal(
            "signal_combiner",
            sym if "NSE:" not in best.symbol else best.symbol,
            action,
            best.rail,
            conf,
            f"net_{action}_{len(set(contributors))}strat",
            meta={
                "net_score": round(net, 4),
                "buy_score": round(buy_score, 4),
                "sell_score": round(sell_score, 4),
                "contributors": list(dict.fromkeys(contributors))[:8],
            },
        )

    def _position_guard(self, sym: str, signal: Signal, ctx: MarketContext) -> Optional[Signal]:
        pos = (ctx.positions or {}).get(sym) or {}
        qty = int(pos.get("qty", 0) or 0)
        if signal.action == "BUY" and qty > 0:
            return None
        if signal.action == "SELL" and qty <= 0:
            return None
        return signal

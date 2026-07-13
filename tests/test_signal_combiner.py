"""Signal combiner unit tests."""
from __future__ import annotations

from src.agent.signal_combiner import SignalCombiner
from src.strategies.base import MarketContext, Signal


def _sig(sid: str, action: str, conf: float, sym: str = "INFY") -> Signal:
    return Signal(sid, sym, action, "MIS", conf, sid)


def test_net_cancels_buy_sell_churn():
    combiner = SignalCombiner(window_ms=500)
    ctx = MarketContext()
    weights = {"a": 1.0, "b": 1.0}
    signals = [_sig("a", "BUY", 0.7), _sig("b", "SELL", 0.72)]
    out = combiner.combine(signals, ctx, weights, lambda s: s.confidence)
    assert out == []


def test_net_buy_wins():
    combiner = SignalCombiner(window_ms=500)
    ctx = MarketContext()
    weights = {"a": 1.0, "b": 1.0}
    signals = [_sig("a", "BUY", 0.8), _sig("b", "SELL", 0.4)]
    out = combiner.combine(signals, ctx, weights, lambda s: s.confidence)
    assert len(out) == 1
    assert out[0].action == "BUY"
    assert out[0].strategy_id == "signal_combiner"


def test_blocks_duplicate_buy_when_long():
    combiner = SignalCombiner(window_ms=500)
    ctx = MarketContext(positions={"INFY": {"qty": 10, "avg_price": 100}})
    out = combiner.combine([_sig("a", "BUY", 0.8)], ctx, {}, lambda s: s.confidence)
    assert out == []

"""
Walk-forward momentum backtest — same feature/score path as live screener.

T+1 execution, Zerodha costs, benchmark vs NIFTYBEES buy-hold (trading-bot pattern).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..costs.cost_engine import CostEngine
from ..features.feature_store import FeatureStore
from ..portfolio.sizing import inverse_vol_weights, rupee_qty_map

logger = logging.getLogger("bharatquant.backtest")


@dataclass
class BacktestConfig:
    initial_cash: float = 10_000.0
    daily_budget: float = 1000.0
    max_positions: int = 5
    max_rupees_per_trade: float = 1000.0
    min_score: float = 0.65
    rebalance_days: int = 21
    slippage_bps: int = 4
    benchmark_symbol: str = "NIFTYBEES"


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    benchmark_curve: pd.Series
    trades: pd.DataFrame
    metrics: Dict[str, float]


def _score_row(feats: dict) -> float:
    return float(
        0.4 * feats.get("r3m", 0)
        + 0.4 * feats.get("r1m", 0)
        + 0.1 * (feats.get("rsi", 50) / 100.0)
        + 0.1 * feats.get("ma_align", 0)
    )


def run_walk_forward(
    price_panel: pd.DataFrame,
    cfg: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """
    price_panel: columns = symbols, index = datetime dates, values = close prices.
    """
    cfg = cfg or BacktestConfig()
    fs = FeatureStore()
    costs = CostEngine(slippage_bps=cfg.slippage_bps)
    dates = sorted(price_panel.index)
    if len(dates) < 220:
        raise ValueError("Need ≥220 trading days for walk-forward")

    cash = cfg.initial_cash
    holdings: Dict[str, int] = {}
    avg_cost: Dict[str, float] = {}
    trades: List[dict] = []
    equity: List[tuple] = []
    bench_start = float(price_panel[cfg.benchmark_symbol].iloc[0]) if cfg.benchmark_symbol in price_panel.columns else 1.0
    bench_units = cfg.initial_cash / bench_start if bench_start > 0 else 0.0

    last_rebal = -cfg.rebalance_days

    for i, dt in enumerate(dates):
        prices_today = price_panel.loc[dt].dropna().astype(float)
        port_value = cash + sum(holdings.get(s, 0) * prices_today.get(s, 0) for s in holdings if s in prices_today)
        equity.append((dt, port_value))

        if i - last_rebal < cfg.rebalance_days or i < 200:
            continue
        last_rebal = i

        hist_end = i
        hist_start = max(0, hist_end - 250)
        window = price_panel.iloc[hist_start:hist_end]
        scores: List[tuple] = []
        for sym in window.columns:
            if sym == cfg.benchmark_symbol:
                continue
            col = window[sym].dropna()
            if len(col) < 200:
                continue
            df = pd.DataFrame(
                {
                    "date": col.index,
                    "open": col.values,
                    "high": col.values,
                    "low": col.values,
                    "close": col.values,
                    "volume": 1,
                }
            )
            feats = fs.compute_features(df)
            sc = _score_row(feats)
            if sc >= cfg.min_score:
                scores.append((sc, sym))

        if not scores:
            continue

        scores.sort(reverse=True)
        picks = [s for _, s in scores[: cfg.max_positions * 3]]
        sub = window[picks].dropna(how="all").ffill().dropna(how="any")
        if sub.empty:
            continue
        weights = inverse_vol_weights(sub, max_names=cfg.max_positions)
        if not weights:
            continue

        px_map = {s: float(prices_today[s]) for s in weights if s in prices_today and prices_today[s] > 0}
        qty_map = rupee_qty_map(weights, px_map, cfg.daily_budget, min_qty=1)

        # Sell names not in target
        for sym, q in list(holdings.items()):
            if sym not in qty_map and sym in prices_today:
                sell_px = prices_today[sym] * (1 - cfg.slippage_bps / 10_000)
                proceeds = sell_px * q - costs.compute_trade_costs(sym, q, sell_px, "SELL")
                cash += proceeds
                trades.append({"date": dt, "symbol": sym, "side": "SELL", "qty": q, "price": sell_px})
                del holdings[sym]
                avg_cost.pop(sym, None)

        for sym, target_q in qty_map.items():
            if sym not in prices_today:
                continue
            cur_q = holdings.get(sym, 0)
            cap_q = max(1, int(cfg.max_rupees_per_trade // prices_today[sym]))
            target_q = min(target_q, cap_q)
            delta = target_q - cur_q
            if delta <= 0:
                continue
            buy_px = float(prices_today[sym]) * (1 + cfg.slippage_bps / 10_000)
            fee = costs.compute_trade_costs(sym, delta, buy_px, "BUY")
            cost = buy_px * delta + fee
            if cost > cash:
                continue
            cash -= cost
            holdings[sym] = cur_q + delta
            avg_cost[sym] = buy_px
            trades.append({"date": dt, "symbol": sym, "side": "BUY", "qty": delta, "price": buy_px})

    eq = pd.Series({d: v for d, v in equity}, name="equity")
    bench = pd.Series(
        {
            d: bench_units * float(price_panel.loc[d, cfg.benchmark_symbol])
            for d in dates
            if cfg.benchmark_symbol in price_panel.columns
        },
        name="benchmark",
    )
    rets = eq.pct_change().dropna()
    bench_rets = bench.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    max_dd = float(((eq / eq.cummax()) - 1).min()) if len(eq) else 0.0
    total_ret = float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) > 1 else 0.0
    bench_ret = float(bench.iloc[-1] / bench.iloc[0] - 1) if len(bench) > 1 else 0.0

    return BacktestResult(
        equity_curve=eq,
        benchmark_curve=bench,
        trades=pd.DataFrame(trades),
        metrics={
            "total_return_pct": total_ret * 100,
            "benchmark_return_pct": bench_ret * 100,
            "sharpe": sharpe,
            "max_drawdown_pct": max_dd * 100,
            "n_trades": len(trades),
        },
    )


def run_registry_historical_screen(db, **kwargs) -> list[dict]:
    """
    Screen every built-in registry strategy on backfilled bar_log history.
    Pre-screen priority only — does not alter capital_gate or lifecycle promotion.
    """
    from .strategy_screen import run_registry_screen

    return run_registry_screen(db, **kwargs)

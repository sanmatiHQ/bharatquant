"""Per-strategy historical replay on bar_log — Sortino/Calmar/p-value for pre-screen priority."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional, Type

from ..agent.strategy_stats import binomial_edge_p_value
from ..db.database import DB
from ..events.types import EventType, MarketEvent
from ..risk.risk_metrics import fitness_from_returns, periods_per_year_discovery
from ..strategies.base import MarketContext, Signal, Strategy
from ..strategies.registry import _BUILTIN

logger = logging.getLogger("bharatquant.strategy_screen")
_MAX_SCREEN_SAMPLES = int(os.getenv("HIST_SCREEN_MAX_SAMPLES", "5000"))
_MAX_BARS_PER_SYMBOL = int(os.getenv("HIST_SCREEN_MAX_BARS", "8000"))
_REPLAY_STRIDE = max(1, int(os.getenv("HIST_SCREEN_REPLAY_STRIDE", "5")))


@dataclass
class StrategyScreenResult:
    strategy_id: str
    sample_count: int
    win_rate: float
    sortino: float
    calmar: float
    max_drawdown_pct: float
    binomial_p: float
    composite: float
    cleared: bool
    status: str
    interval: str
    lookback_days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "sample_count": self.sample_count,
            "win_rate": round(self.win_rate, 4),
            "sortino": round(self.sortino, 4),
            "calmar": round(self.calmar, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "binomial_p": round(self.binomial_p, 6),
            "composite": round(self.composite, 4),
            "cleared": self.cleared,
            "status": self.status,
            "interval": self.interval,
            "lookback_days": self.lookback_days,
        }


def _rsi(closes: list[float], idx: int, period: int = 14) -> float:
    if idx < period:
        return 50.0
    gains = losses = 0.0
    for j in range(idx - period + 1, idx + 1):
        d = closes[j] - closes[j - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = (gains / period) / (losses / period)
    return 100.0 - (100.0 / (1.0 + rs))


def _payload_at(closes: list[float], highs: list[float], lows: list[float], vols: list[float], idx: int) -> dict:
    c0 = closes[idx]
    r3m = (c0 - closes[idx - 3]) / closes[idx - 3] if idx >= 3 and closes[idx - 3] else 0.0
    r1m = (c0 - closes[idx - 1]) / closes[idx - 1] if idx >= 1 and closes[idx - 1] else 0.0
    hi, lo = highs[idx], lows[idx]
    rng = max(hi - lo, 0.0)
    ibs = (c0 - lo) / rng if rng > 0 else 0.5
    tail = closes[max(0, idx - 19) : idx + 1]
    z = 0.0
    if len(tail) >= 5:
        m = sum(tail) / len(tail)
        var = sum((x - m) ** 2 for x in tail) / len(tail)
        sd = var**0.5
        z = (c0 - m) / sd if sd > 0 else 0.0
    ranges = [max(highs[j] - lows[j], 0.0) for j in range(max(0, idx - 6), idx + 1)]
    nr7 = 1 if ranges and ranges[-1] <= min(ranges) * 1.001 else 0
    vol_avg = sum(vols[max(0, idx - 19) : idx + 1]) / min(20, idx + 1) if vols else 1.0
    vol_ratio = vols[idx] / vol_avg if vol_avg else 1.0
    return {
        "open": closes[max(0, idx - 1)],
        "high": hi,
        "low": lo,
        "close": c0,
        "volume": vols[idx],
        "r3m": r3m,
        "r1m": r1m,
        "rsi": _rsi(closes, idx),
        "ibs": ibs,
        "z_score": z,
        "nr7": nr7,
        "vol_ratio": vol_ratio,
        "ema_cross_up": 0,
        "donchian_brk": 0,
        "near_high_20": 0,
        "lower_high_streak": 0,
    }


def _screenable(strategy: Strategy) -> bool:
    evs = strategy.listens_to
    return bool(
        EventType.BAR_CLOSE_5M in evs
        or EventType.BAR_CLOSE_1D in evs
        or EventType.TICK in evs
        or EventType.VWAP_CROSS in evs
    )


async def _replay_symbol(
    strategy: Strategy,
    ctx: MarketContext,
    bars: list[dict],
    *,
    forward_bars: int = 3,
) -> list[float]:
    if len(bars) < 40:
        return []
    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    vols = [float(b.get("volume") or 0) for b in bars]
    sym = str(bars[0]["symbol"])
    rets: list[float] = []
    listens = strategy.listens_to
    for i in range(20, len(bars) - forward_bars, _REPLAY_STRIDE):
        payload = _payload_at(closes, highs, lows, vols, i)
        ts = int(bars[i]["ts"])
        px = closes[i]
        signals: list[Optional[Signal]] = []
        if EventType.BAR_CLOSE_5M in listens or EventType.BAR_CLOSE_1D in listens:
            signals.append(
                await strategy.on_event(
                    MarketEvent(type=EventType.BAR_CLOSE_5M, symbol=sym, price=px, ts=ts, payload=payload),
                    ctx,
                )
            )
        if EventType.TICK in listens:
            signals.append(
                await strategy.on_event(
                    MarketEvent(type=EventType.TICK, symbol=sym, price=px, ts=ts, payload={}),
                    ctx,
                )
            )
        if EventType.VWAP_CROSS in listens:
            signals.append(
                await strategy.on_event(
                    MarketEvent(
                        type=EventType.VWAP_CROSS,
                        symbol=sym,
                        price=px,
                        ts=ts,
                        payload={"vwap": px, "side": "above"},
                    ),
                    ctx,
                )
            )
        for sig in signals:
            if not sig or sig.action != "BUY":
                continue
            c0, c1 = closes[i], closes[i + forward_bars]
            if c0 <= 0:
                continue
            rets.append((c1 - c0) / c0)
    return rets


async def screen_strategy(
    db: DB,
    strategy: Strategy,
    symbols: list[str],
    *,
    interval: str = "5m",
    forward_bars: int = 3,
    lookback_days: int = 365,
) -> StrategyScreenResult:
    cutoff = int(time.time()) - lookback_days * 86400
    ctx = MarketContext(
        regime="BULL",
        india_vix=14.0,
        fii_net_cr=800.0,
        dii_net_cr=400.0,
        gift_nifty_change_pct=0.1,
        market_open=True,
        session_phase="regular",
    )
    if not _screenable(strategy):
        return StrategyScreenResult(
            strategy_id=strategy.id,
            sample_count=0,
            win_rate=0.0,
            sortino=0.0,
            calmar=0.0,
            max_drawdown_pct=0.0,
            binomial_p=1.0,
            composite=0.0,
            cleared=False,
            status="event_feed_required",
            interval=interval,
            lookback_days=lookback_days,
        )
    all_rets: list[float] = []
    for sym in symbols:
        rows = db._conn.execute(
            """
            SELECT ts, symbol, open, high, low, close, volume FROM (
              SELECT ts, symbol, open, high, low, close, volume FROM bar_log
              WHERE symbol=? AND interval=? AND ts >= ?
              ORDER BY ts DESC LIMIT ?
            ) sub ORDER BY ts ASC
            """,
            (sym, interval, cutoff, _MAX_BARS_PER_SYMBOL),
        ).fetchall()
        if len(rows) < 40:
            continue
        bars = [dict(r) for r in rows]
        all_rets.extend(await _replay_symbol(strategy, ctx, bars, forward_bars=forward_bars))

    n = len(all_rets)
    if n < 5:
        return StrategyScreenResult(
            strategy_id=strategy.id,
            sample_count=n,
            win_rate=0.0,
            sortino=0.0,
            calmar=0.0,
            max_drawdown_pct=0.0,
            binomial_p=1.0,
            composite=0.0,
            cleared=False,
            status="insufficient_bars",
            interval=interval,
            lookback_days=lookback_days,
        )
    metric_rets = all_rets
    if n > _MAX_SCREEN_SAMPLES:
        step = max(1, n // _MAX_SCREEN_SAMPLES)
        metric_rets = all_rets[::step][:_MAX_SCREEN_SAMPLES]
    wins = sum(1 for r in all_rets if r > 0)
    win_rate = wins / n
    ppy = periods_per_year_discovery(len(metric_rets), lookback_days) if interval == "5m" else 252.0
    fit = fitness_from_returns(metric_rets, periods_per_year=ppy)
    pval = binomial_edge_p_value(wins, n)
    cleared = n >= 20 and fit.composite >= 0.15 and pval < 0.05
    return StrategyScreenResult(
        strategy_id=strategy.id,
        sample_count=n,
        win_rate=win_rate,
        sortino=fit.sortino,
        calmar=fit.calmar,
        max_drawdown_pct=fit.max_drawdown * 100.0,
        binomial_p=pval,
        composite=fit.composite,
        cleared=cleared,
        status="ok" if n >= 20 else "low_sample",
        interval=interval,
        lookback_days=lookback_days,
    )


def _instantiate_strategy(sid: str, db: DB) -> Optional[Strategy]:
    cls: Optional[Type[Strategy]] = _BUILTIN.get(sid)
    if not cls:
        return None
    if sid in ("strategy_lab", "sector_rotation", "options_greeks", "pairs_stat_arb", "affordable_momentum"):
        return cls(db=db)
    return cls()


def _screen_symbols(db: DB, limit: int = 40) -> list[str]:
    rows = db._conn.execute(
        """
        SELECT symbol, COUNT(*) AS n FROM bar_log
        WHERE interval='5m' GROUP BY symbol ORDER BY n DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if rows:
        return [str(r["symbol"]) for r in rows]
    rows = db._conn.execute(
        """
        SELECT symbol, COUNT(*) AS n FROM bar_log
        WHERE interval='1d' GROUP BY symbol ORDER BY n DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [str(r["symbol"]) for r in rows]


async def screen_all_registry(
    db: DB,
    *,
    strategy_ids: Optional[list[str]] = None,
    symbol_limit: int = 40,
    lookback_days: int = 365,
) -> list[StrategyScreenResult]:
    ids = strategy_ids or list(_BUILTIN.keys())
    symbols = _screen_symbols(db, symbol_limit)
    n5 = int(
        db._conn.execute("SELECT COUNT(*) AS n FROM bar_log WHERE interval='5m'").fetchone()["n"] or 0
    )
    interval = "5m" if n5 > 100 else "1d"
    out: list[StrategyScreenResult] = []
    for sid in ids:
        strat = _instantiate_strategy(sid, db)
        if not strat:
            continue
        res = await screen_strategy(
            db, strat, symbols, interval=interval, lookback_days=lookback_days
        )
        out.append(res)
        persist_screen_results(db, [res])
    return out


def persist_screen_results(db: DB, results: list[StrategyScreenResult]) -> int:
    ts = int(time.time())
    n = 0
    with db.tx() as conn:
        for r in results:
            d = r.to_dict()
            conn.execute(
                """
                INSERT INTO historical_screen(
                  strategy_id, screened_ts, interval, sample_count, win_rate,
                  sortino, calmar, max_drawdown_pct, binomial_p, composite,
                  cleared, status, lookback_days
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                  screened_ts=excluded.screened_ts,
                  interval=excluded.interval,
                  sample_count=excluded.sample_count,
                  win_rate=excluded.win_rate,
                  sortino=excluded.sortino,
                  calmar=excluded.calmar,
                  max_drawdown_pct=excluded.max_drawdown_pct,
                  binomial_p=excluded.binomial_p,
                  composite=excluded.composite,
                  cleared=excluded.cleared,
                  status=excluded.status,
                  lookback_days=excluded.lookback_days
                """,
                (
                    d["strategy_id"],
                    ts,
                    d["interval"],
                    d["sample_count"],
                    d["win_rate"],
                    d["sortino"],
                    d["calmar"],
                    d["max_drawdown_pct"],
                    d["binomial_p"],
                    d["composite"],
                    int(d["cleared"]),
                    d["status"],
                    d["lookback_days"],
                ),
            )
            n += 1
    return n


def run_registry_screen(db: DB, **kwargs) -> list[dict]:
    """Sync entrypoint for scripts and walk_forward integration."""
    results = asyncio.run(screen_all_registry(db, **kwargs))
    persist_screen_results(db, results)
    return [r.to_dict() for r in results]

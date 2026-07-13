"""Manual paper trades + user symbol queue for agent prioritization."""
from __future__ import annotations

import json
import os
import time
from typing import Any

from ..accounting.fifo_lots import open_lot
from ..costs.cost_engine import CostEngine
from ..db.database import DB
from ..exec.paper_broker import PaperBroker
from ..ops.agent_state import persist_decision


def lookup_symbol(db: DB, symbol: str) -> dict[str, Any]:
    sym = symbol.upper().replace("NSE:", "")
    tick = db._conn.execute(
        "SELECT ltp, ts FROM tick_log WHERE symbol=? ORDER BY ts DESC LIMIT 1",
        (sym,),
    ).fetchone()
    pos = db._conn.execute(
        "SELECT qty, avg_price, last_price FROM positions WHERE symbol=?", (sym,)
    ).fetchone()
    screen = db._conn.execute(
        """
        SELECT momentum_score, r1m, r3m, rsi FROM screening_results
        WHERE symbol=? ORDER BY run_ts DESC LIMIT 1
        """,
        (sym,),
    ).fetchone()
    fund = db._conn.execute(
        "SELECT roe, pe, market_cap_cr FROM fundamentals_cache WHERE symbol=?", (sym,)
    ).fetchone()
    sigs = [
        dict(r)
        for r in db._conn.execute(
            """
            SELECT strategy_id, signal, confidence, executed, reason, ts
            FROM strategy_ledger WHERE symbol=? ORDER BY ts DESC LIMIT 5
            """,
            (sym,),
        ).fetchall()
    ]
    bars = db._conn.execute(
        "SELECT COUNT(*) c FROM bar_log WHERE symbol=? AND interval='5m'",
        (sym,),
    ).fetchone()["c"]
    in_universe = _in_universe(sym)
    return {
        "symbol": sym,
        "ltp": float(tick["ltp"]) if tick else None,
        "last_tick_ts": int(tick["ts"]) if tick else None,
        "position": dict(pos) if pos else None,
        "momentum_score": float(screen["momentum_score"]) if screen else None,
        "screen_metrics": dict(screen) if screen else None,
        "fundamentals": dict(fund) if fund else None,
        "recent_signals": sigs,
        "bars_5m": int(bars),
        "in_universe": in_universe,
        "affordable_whole_shares": _affordable_qty(db, sym, float(tick["ltp"]) if tick else 0),
    }


def _in_universe(sym: str) -> bool:
    import csv
    from pathlib import Path

    tier = os.getenv("UNIVERSE_TIER", "main")
    paths = {
        "main": "data/universe_full_nse.csv",
        "with_sme": "data/universe_full_nse_sme.csv",
        "all_eq": "data/universe_all_nse_eq.csv",
    }
    path = Path(os.getenv("UNIVERSE", paths.get(tier, paths["main"])))
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("symbol", "").upper() == sym:
                return True
    return False


def _affordable_qty(db: DB, sym: str, ltp: float) -> int:
    if ltp <= 0:
        return 0
    cash = float(db._conn.execute("SELECT IFNULL(SUM(delta),0) FROM cash_ledger").fetchone()[0])
    max_trade = float(os.getenv("MAX_RUPEES_PER_TRADE", "2500"))
    cap = min(max_trade, cash * 0.92)
    if cap < ltp:
        return 0
    return int(cap // ltp)


def queue_symbol_for_agent(db: DB, symbol: str, note: str = "") -> dict:
    sym = symbol.upper().replace("NSE:", "")
    raw = db._conn.execute("SELECT v FROM settings WHERE k='agent_symbol_queue'").fetchone()
    queue: list[dict] = []
    if raw:
        try:
            queue = json.loads(raw["v"])
        except json.JSONDecodeError:
            queue = []
    entry = {"symbol": sym, "note": note, "ts": int(time.time())}
    queue = [q for q in queue if q.get("symbol") != sym]
    queue.insert(0, entry)
    queue = queue[:20]
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings(k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("agent_symbol_queue", json.dumps(queue)),
        )
    persist_decision(db, {"action": "USER_QUEUE", "symbol": sym, "note": note})
    return {"queued": sym, "queue_len": len(queue)}


def get_symbol_queue(db: DB) -> list[dict]:
    raw = db._conn.execute("SELECT v FROM settings WHERE k='agent_symbol_queue'").fetchone()
    if not raw:
        return []
    try:
        return json.loads(raw["v"])
    except json.JSONDecodeError:
        return []


def execute_manual_paper_buy(db: DB, symbol: str, qty: int | None = None, reason: str = "manual_dashboard") -> dict:
    from ..ops.kill_switch import is_halted

    if is_halted(db):
        return {"ok": False, "error": "trading_halted"}
    sym = symbol.upper().replace("NSE:", "")
    tick = db._conn.execute(
        "SELECT ltp FROM tick_log WHERE symbol=? ORDER BY ts DESC LIMIT 1",
        (sym,),
    ).fetchone()
    if not tick:
        return {"ok": False, "error": "no_ltp", "hint": "Symbol not in tick feed — queue for agent or wait for WS"}
    ltp = float(tick["ltp"])
    if qty is None or qty <= 0:
        qty = _affordable_qty(db, sym, ltp)
    if qty <= 0:
        return {"ok": False, "error": "affordability", "ltp": ltp, "hint": "Whole shares only — insufficient cash for 1 share"}
    cash = float(db._conn.execute("SELECT IFNULL(SUM(delta),0) FROM cash_ledger").fetchone()[0])
    cost_est = ltp * qty
    if cost_est > cash:
        return {"ok": False, "error": "insufficient_cash", "need": cost_est, "cash": cash}

    from .budget_gate import can_deploy

    ok_b, b_reason = can_deploy(db, cost_est)
    if not ok_b:
        return {"ok": False, "error": "daily_budget_cap", "reason": b_reason}

    paper = PaperBroker(slippage_bps=int(os.getenv("SLIPPAGE_BPS", "4")))
    costs = CostEngine(slippage_bps=int(os.getenv("SLIPPAGE_BPS", "4")))
    ts = int(time.time())
    exec_px = paper.buy(sym, qty, ltp)
    fees = costs.compute_trade_costs(sym, qty, exec_px, "BUY", order_id=f"MANUAL-B-{ts}")
    total = exec_px * qty + fees
    order_id = f"MANUAL-B-{ts}"
    tid = db.record_trade(ts, sym, "BUY", qty, exec_px, total, reason, fees, "NA", order_id=order_id)
    db.add_cash(ts, -total, f"manual_buy:{sym}")
    open_lot(db, sym, qty, exec_px, ts, "CNC", tid)
    persist_decision(db, {"action": "MANUAL_BUY", "symbol": sym, "qty": qty, "price": exec_px, "reason": reason})
    return {"ok": True, "symbol": sym, "qty": qty, "price": exec_px, "fees": fees, "order_id": order_id}

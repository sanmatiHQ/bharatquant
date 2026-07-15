"""FastAPI dashboard — login page, trading console, Kite OAuth callback."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ..auth.kite_auth import build_login_url
from ..db.database import DB, DBConfig
from ..ops.kill_switch import clear_halt, halt_status, is_halted, set_halt
from ..strategies.registry import strategy_count
from .dashboard_styles import DASHBOARD_CSS


class HaltBody(BaseModel):
    reason: str = "manual"


class SuggestBody(BaseModel):
    symbol: str
    side: str = "BUY"
    thesis: str = ""


class ManualBuyBody(BaseModel):
    symbol: str
    qty: int | None = None
    reason: str = "manual_dashboard"


class AgentQueueBody(BaseModel):
    symbol: str
    note: str = ""


class BudgetApproveBody(BaseModel):
    new_max: float | None = None


class SlumberBody(BaseModel):
    minutes: int = 60
    reason: str = "dashboard_slumber"


class AdminLoginBody(BaseModel):
    username: str
    password: str


def _token_status() -> dict:
    from ..ops.healthchecks import check_token

    path = Path(os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json"))
    ts = None
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            ts = raw.get("ts")
        except json.JSONDecodeError:
            pass
    return {"valid": check_token(), "file": str(path), "saved_ts": ts}


def create_app() -> FastAPI:
    app = FastAPI(title="BharatQuant", version="0.5.0")
    logger = logging.getLogger("bharatquant.dashboard")
    db = DB(DBConfig(sqlite_path=os.getenv("SQLITE_PATH", "data/trading.db")))
    halt_secret = os.getenv("HALT_API_SECRET", "")
    api_key = os.getenv("KITE_API_KEY", "")

    from .dashboard_auth import (
        authenticate,
        clear_admin_cookie,
        credentials_configured,
        is_admin_request,
        require_admin,
        session_info,
        set_admin_cookie,
    )

    @app.get("/api/feed/fast")
    def feed_fast():
        from .dashboard_feed import build_live_feed_fast

        return build_live_feed_fast(db)

    @app.get("/api/feed/live")
    def feed_live():
        from .dashboard_feed import build_live_feed

        return build_live_feed(db)

    @app.get("/api/feed/stream")
    async def feed_stream():
        """Server-Sent Events — push telemetry when feed hash changes (~1s)."""
        import asyncio
        import hashlib

        from fastapi.responses import StreamingResponse

        from .dashboard_feed import build_live_feed_fast

        async def _gen():
            last = ""
            yield ": connected\n\n"
            while True:
                try:
                    payload = await asyncio.to_thread(build_live_feed_fast, db)
                    payload["transport"] = "sse"
                    blob = json.dumps(payload, sort_keys=True, default=str)
                    h = hashlib.md5(blob.encode()).hexdigest()
                    if h != last:
                        yield f"data: {blob}\n\n"
                        last = h
                except Exception:
                    logger.exception("sse_feed_error")
                await asyncio.sleep(1)

        return StreamingResponse(_gen(), media_type="text/event-stream")

    @app.websocket("/ws/feed")
    async def ws_feed(websocket: WebSocket):
        from .dashboard_feed import build_live_feed
        from .ws_broadcast import feed_manager

        await feed_manager.connect_ws(websocket)
        try:
            snap = build_live_feed(db)
            snap["transport"] = "ws"
            await websocket.send_text(json.dumps(snap, default=str))
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await feed_manager.disconnect_ws(websocket)
        except Exception:
            await feed_manager.disconnect_ws(websocket)

    @app.get("/api/admin/session")
    def admin_session(request: Request):
        return session_info(request)

    @app.post("/api/admin/login")
    def admin_login(body: AdminLoginBody, response: Response):
        if not credentials_configured():
            raise HTTPException(
                status_code=503,
                detail="Set DASHBOARD_ADMIN_USER and DASHBOARD_ADMIN_PASSWORD in env",
            )
        if not authenticate(body.username, body.password):
            raise HTTPException(status_code=401, detail="invalid credentials")
        set_admin_cookie(response, body.username)
        return {"ok": True}

    @app.post("/api/admin/logout")
    def admin_logout(response: Response):
        clear_admin_cookie(response)
        return {"ok": True}

    @app.get("/admin", response_class=HTMLResponse)
    def admin_login_page():
        from .dashboard_template import render_admin_login

        return HTMLResponse(render_admin_login(DASHBOARD_CSS))

    def _check_halt_auth(x_halt_secret: str | None) -> None:
        if halt_secret and x_halt_secret != halt_secret:
            raise HTTPException(status_code=403, detail="invalid halt secret")

    @app.get("/health")
    def health():
        from ..ops.healthchecks import check_db, check_token

        return {
            "status": "ok",
            "mode": os.getenv("TRADING_MODE", "paper"),
            "halted": is_halted(db),
            "kite_token": check_token(),
            "db": check_db(),
            "gcp_project": os.getenv("GCP_PROJECT_ID", ""),
            "gcp_static_ip": os.getenv("GCP_STATIC_IP", ""),
            "gcs_bucket": os.getenv("GCS_BACKUP_BUCKET", ""),
        }

    @app.get("/api/auth/status")
    def auth_status():
        st = _token_status()
        static_ip = os.getenv("GCP_STATIC_IP", "")
        return {
            **st,
            "mode": os.getenv("TRADING_MODE", "paper"),
            "login_url": build_login_url(api_key) if api_key else None,
            "redirect_url": os.getenv("KITE_REDIRECT_URL", ""),
            "whitelist_ip": static_ip,
            "kite_console": "https://developers.kite.trade/apps",
        }

    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        login_url = build_login_url(api_key) if api_key else "#"
        redirect = os.getenv("KITE_REDIRECT_URL", "http://127.0.0.1:8080/kite/callback")
        static_ip = os.getenv("GCP_STATIC_IP", "")
        mode = os.getenv("TRADING_MODE", "paper")
        ip_block = ""
        if static_ip:
            ip_block = f"""
    <div class="card" style="border-color:rgba(251,191,36,0.4)">
      <div class="label">Zerodha — register this VM IP (required)</div>
      <p style="margin:0.5rem 0;font-size:1.25rem;font-weight:700;font-family:monospace">{static_ip}</p>
      <p class="notice">
        <strong>Kite developer console</strong> → your app → <em>IP whitelist</em> → add only:<br>
        <code>{static_ip}</code> (one line, no port, no https)<br>
        Redirect URL (must be <strong>HTTPS</strong>): <code>{redirect}</code><br>
        <strong>Do not use</strong> <code>http://{static_ip}:8080/...</code> — Kite rejects non-HTTPS public URLs. Use the HTTPS host above.<br>
        Postback URL: leave blank for now (optional).<br>
        <a href="https://developers.kite.trade/apps" target="_blank">developers.kite.trade/apps</a>
      </p>
    </div>"""
        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Login — BharatQuant</title><style>{DASHBOARD_CSS}</style></head>
<body>
  <div class="login-wrap">
  <div class="panel login-card">
      <h1 style="margin:0 0 0.5rem;text-align:center">BharatQuant</h1>
      <p class="muted" style="text-align:center">Connect Zerodha Kite for live ticks and trading.</p>
      <p id="authStatus" style="margin:0.75rem 0;text-align:center">Checking…</p>
      <a id="kiteBtn" class="btn full" href="{login_url}">Connect Zerodha Kite</a>
      <p class="muted" style="margin-top:1rem;font-size:0.8rem">
        Redirect after login:<br><code>{redirect}</code>
      </p>
    </div>
    {ip_block}
    <div class="panel login-card">
      <div class="label">Trading mode</div>
      <p><span class="badge ok">{mode.upper()}</span> — paper uses simulated orders.</p>
    </div>
    <p class="muted" style="text-align:center"><a href="/dashboard">→ Public dashboard</a></p>
  </div>
  <script>
    async function refresh() {{
      const s = await fetch('/api/auth/status').then(r => r.json());
      const el = document.getElementById('authStatus');
      const btn = document.getElementById('kiteBtn');
      if (s.valid) {{
        el.innerHTML = '<span class="badge ok">TOKEN ACTIVE</span> Saved at ' + (s.saved_ts ? new Date(s.saved_ts*1000).toLocaleString() : '—');
        btn.textContent = 'Re-connect Kite';
      }} else {{
        el.innerHTML = '<span class="badge err">NO TOKEN</span> Login required for live quotes & orders.';
        btn.textContent = 'Connect Zerodha Kite';
      }}
    }}
    refresh();
    setInterval(refresh, 10000);
  </script>
</body></html>"""

    @app.get("/kite/callback")
    def kite_callback(request_token: str = "", status: str = ""):
        if not request_token:
            raise HTTPException(status_code=400, detail="missing request_token")
        if status and status != "success":
            raise HTTPException(status_code=400, detail=f"login status={status}")

        from ..auth.kite_auth import exchange_token

        api_secret = os.getenv("KITE_API_SECRET", "")
        token_file = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
        if not api_key or not api_secret:
            raise HTTPException(status_code=500, detail="KITE_API_KEY/SECRET not configured")

        try:
            access = exchange_token(api_key, api_secret, request_token)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"token exchange failed: {exc}") from exc

        path = Path(token_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"data": {"access_token": access}, "ts": int(time.time())}),
            encoding="utf-8",
        )
        from ..ops.healthchecks import invalidate_token_cache

        invalidate_token_cache()
        restart_flag = Path(os.getenv("LOGS_DIR", "logs")) / "engine_restart.flag"
        restart_flag.parent.mkdir(parents=True, exist_ok=True)
        restart_flag.write_text(str(int(time.time())), encoding="utf-8")
        return HTMLResponse(
            f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Login OK</title>
            <meta http-equiv="refresh" content="3;url=/dashboard"/>
            <style>{DASHBOARD_CSS}</style></head><body><div class="wrap" style="margin-top:3rem">
            <div class="card"><h2>Login successful</h2>
            <p>Kite connected. Token saved — live ticks reconnect in ~10s.</p>
            <p class="muted">Redirecting to dashboard…</p>
            <a class="btn" href="/dashboard">Open dashboard now</a>
            </div></div></body></html>"""
        )

    @app.get("/api/overview")
    def overview():
        from ..ops.daily_pnl import portfolio_state

        st = portfolio_state(db)
        conn = db._conn
        buy = float(conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY'").fetchone()[0])
        sell = float(conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='SELL'").fetchone()[0])
        unrealized = float(
            conn.execute("SELECT IFNULL(SUM((last_price-avg_price)*qty),0) FROM positions").fetchone()[0]
        )
        return {
            "cash": st["cash"],
            "holdings_value": st["holdings_value"],
            "total_value": st["total_equity"],
            "realized_pnl": sell - buy,
            "unrealized_pnl": unrealized,
            "day_loss_rupees": st["day_loss_rupees"],
            **halt_status(db),
        }

    @app.get("/api/positions")
    def positions():
        cur = db._conn.execute("SELECT symbol, qty, avg_price, last_price, open_ts FROM positions")
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/indices")
    def indices():
        from ..ingest.index_data import INDEX_MAP

        out = []
        for key, meta in INDEX_MAP.items():
            sym = meta["db_symbol"]
            latest = db._conn.execute(
                "SELECT ltp, ts FROM tick_log WHERE symbol=? ORDER BY ts DESC LIMIT 1", (sym,)
            ).fetchone()
            if not latest:
                out.append({"key": key, "label": meta["label"], "exchange": meta.get("exchange", "NSE"), "ltp": None, "stale": True})
                continue
            day_start = int(latest["ts"]) - (int(latest["ts"]) % 86400)
            day_open_row = db._conn.execute(
                "SELECT ltp FROM tick_log WHERE symbol=? AND ts>=? ORDER BY ts ASC LIMIT 1",
                (sym, day_start),
            ).fetchone()
            ltp = float(latest["ltp"])
            day_open = float(day_open_row["ltp"]) if day_open_row else ltp
            chg_abs = ltp - day_open
            chg_pct = (chg_abs / day_open * 100.0) if day_open else 0.0
            out.append({
                "key": key,
                "label": meta["label"],
                "exchange": meta.get("exchange", "NSE"),
                "ltp": ltp,
                "chg_abs": round(chg_abs, 2),
                "chg_pct": round(chg_pct, 2),
                "ts": int(latest["ts"]),
                "stale": (int(time.time()) - int(latest["ts"])) > 900,
            })
        return out

    @app.get("/api/search/{symbol}")
    def search_symbol(symbol: str):
        from ..ops.manual_trade import lookup_symbol

        return lookup_symbol(db, symbol)

    @app.post("/api/manual_trade/suggest")
    def suggest_trade(body: SuggestBody, request: Request):
        require_admin(request)
        from ..ops.manual_trade import create_suggestion

        return create_suggestion(db, body.symbol, body.side, body.thesis)

    @app.get("/api/manual_trade/queue")
    def suggestion_queue(request: Request):
        require_admin(request)
        from ..ops.manual_trade import list_suggestions, resolve_evaluating_suggestions

        resolve_evaluating_suggestions(db)
        return list_suggestions(db)

    @app.get("/api/kite/status")
    def kite_status():
        from ..ops.healthchecks import check_token_fast

        token_path = os.getenv("KITE_ACCESS_TOKEN_FILE", ".kite_token.json")
        valid = check_token_fast()
        refreshed_at = None
        next_expiry_ist = None
        if os.path.exists(token_path):
            mtime = os.path.getmtime(token_path)
            refreshed_at = int(mtime)
            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo

            ist = ZoneInfo("Asia/Kolkata")
            refreshed_dt = datetime.fromtimestamp(mtime, tz=ist)
            expiry_dt = refreshed_dt.replace(hour=7, minute=30, second=0, microsecond=0)
            if expiry_dt <= refreshed_dt:
                expiry_dt += timedelta(days=1)
            next_expiry_ist = expiry_dt.isoformat()
        return {
            "valid": valid,
            "refreshed_at": refreshed_at,
            "next_expiry_ist": next_expiry_ist,
            "totp_configured": bool(os.getenv("KITE_TOTP_SECRET")),
        }

    @app.post("/api/kite/reauth")
    async def kite_reauth(request: Request):
        require_admin(request)
        import asyncio
        import sys

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "src.auth.kite_auth", "--auto",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return {"ok": True, "triggered": True, "pid": proc.pid}

    @app.get("/api/daily_tax_summary")
    def daily_tax_summary():
        from ..ops.daily_tax_summary import build_daily_summary

        return build_daily_summary(db)

    @app.get("/api/gift_gap")
    def gift_gap():
        from ..ingest.market_feed_client import fetch_nse_market_status

        try:
            row = fetch_nse_market_status()
            return {
                "change_pct": row.get("gift_change_pct", 0),
                "gift_last": row.get("gift_last"),
                "gift_timestamp": row.get("gift_timestamp"),
                "source": row.get("source"),
            }
        except Exception:
            cur = db._conn.execute(
                "SELECT payload_json FROM ingest_log WHERE event_type='GIFT_TICK' ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            if not cur:
                return {"change_pct": 0, "source": "none"}
            try:
                p = json.loads(cur["payload_json"])
                return {"change_pct": p.get("change_pct", 0), "source": "ingest_log_cache"}
            except json.JSONDecodeError:
                return {"change_pct": 0}

    @app.get("/api/trades")
    def trades():
        cur = db._conn.execute(
            "SELECT ts, symbol, side, qty, price, amount, reason, order_id FROM trades ORDER BY ts DESC LIMIT 100"
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/strategy_ledger")
    def strategy_ledger():
        cur = db._conn.execute(
            "SELECT ts, strategy_id, symbol, signal, confidence, executed, reason FROM strategy_ledger ORDER BY ts DESC LIMIT 50"
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/portfolio_history")
    def portfolio_history():
        cur = db._conn.execute("SELECT ts, total_value FROM portfolio_history ORDER BY ts ASC LIMIT 90")
        return [{"time": int(r["ts"]), "value": float(r["total_value"])} for r in cur.fetchall()]

    @app.get("/api/allocation")
    def allocation():
        row = db._conn.execute("SELECT MAX(run_ts) AS m FROM portfolio_allocation").fetchone()
        if not row or row["m"] is None:
            return []
        cur = db._conn.execute(
            "SELECT symbol, weight, target_qty, target_rupees, last_price FROM portfolio_allocation WHERE run_ts=? ORDER BY weight DESC",
            (row["m"],),
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/strategy_pnl")
    def strategy_pnl():
        cur = db._conn.execute(
            "SELECT strategy_id, realized_pnl, trade_count FROM strategy_pnl ORDER BY realized_pnl DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/ohlc/{symbol}")
    def ohlc(symbol: str, interval: str = "5m"):
        cur = db._conn.execute(
            "SELECT ts, open, high, low, close FROM bar_log WHERE symbol=? AND interval=? ORDER BY ts ASC LIMIT 200",
            (symbol, interval),
        )
        return [
            {"time": int(r["ts"]), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])}
            for r in cur.fetchall()
        ]

    @app.get("/api/rolling_metrics")
    def rolling_metrics():
        cur = db._conn.execute("SELECT ts, total_value FROM portfolio_history ORDER BY ts ASC LIMIT 60")
        vals = [float(r["total_value"]) for r in cur.fetchall()]
        if len(vals) < 2:
            return {"sharpe": 0, "max_drawdown_pct": 0}
        import numpy as np

        rets = np.diff(vals) / np.array(vals[:-1])
        sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
        peak = np.maximum.accumulate(vals)
        dd = ((np.array(vals) / peak) - 1).min() * 100
        return {"sharpe": sharpe, "max_drawdown_pct": float(dd)}

    @app.get("/api/fii_series")
    def fii_series():
        cur = db._conn.execute(
            "SELECT ts, payload_json FROM ingest_log WHERE event_type='FII_DII_UPDATE' ORDER BY ts DESC LIMIT 30"
        )
        out = []
        for r in cur.fetchall():
            try:
                p = json.loads(r["payload_json"])
                out.append({"ts": r["ts"], "fii_net": p.get("fii_net", 0), "dii_net": p.get("dii_net", 0)})
            except json.JSONDecodeError:
                continue
        return list(reversed(out))

    @app.get("/api/live/pulse")
    def live_pulse():
        from ..ops.market_pulse import load_live_pulse

        return load_live_pulse(db)

    @app.get("/api/agent/status")
    def agent_status():
        from ..ops.agent_state import load_agent_status

        st = load_agent_status(db)
        st["mode"] = os.getenv("TRADING_MODE", "paper")
        st["halted"] = is_halted(db)
        return st

    @app.get("/api/market/session")
    def market_session():
        import asyncio

        from ..feeds.session_watcher import fetch_nse_status
        from ..strategies.market_session import market_clock_snapshot

        try:
            status = asyncio.run(fetch_nse_status())
        except Exception as exc:
            status = f"unknown ({exc})"
        snap = market_clock_snapshot(nse_status=status)
        return {
            **snap,
            "ist_note": "Agent screens on SESSION_PRE_OPEN; trades on TICK during market hours",
        }

    @app.post("/api/halt")
    def api_halt(body: HaltBody, request: Request):
        """Dashboard halt — optional panic square-off of all paper positions."""
        if halt_secret:
            if not is_admin_request(request):
                raise HTTPException(status_code=401, detail="admin login required")
        else:
            require_admin(request)
        if body.reason in ("panic", "dashboard_panic", "panic_halt"):
            from ..ops.panic_halt import panic_halt_and_squareoff

            return panic_halt_and_squareoff(db, reason=body.reason)
        set_halt(db, reason=body.reason)
        return halt_status(db)

    @app.post("/api/resume")
    def api_resume(request: Request):
        if halt_secret:
            if not is_admin_request(request):
                raise HTTPException(status_code=401, detail="admin login required")
        else:
            require_admin(request)
        clear_halt(db)
        return halt_status(db)

    @app.post("/internal/halt")
    def halt_trading(body: HaltBody, x_halt_secret: str | None = Header(default=None)):
        _check_halt_auth(x_halt_secret)
        set_halt(db, reason=body.reason)
        return halt_status(db)

    @app.post("/internal/resume")
    def resume_trading(x_halt_secret: str | None = Header(default=None)):
        _check_halt_auth(x_halt_secret)
        clear_halt(db)
        return halt_status(db)

    @app.get("/api/agent/sandbox")
    def agent_sandbox(recompute: bool = False):
        from ..intelligence.sandbox_review import build_sandbox_review

        return build_sandbox_review(db, recompute=recompute)

    @app.get("/api/agent/learning")
    def agent_learning():
        from ..ops.decision_review import build_learning_review

        return build_learning_review(db)

    @app.get("/api/budget")
    def api_budget():
        from ..ops.budget_gate import budget_status

        return budget_status(db)

    @app.get("/api/trading/phase")
    def api_trading_phase():
        from ..ops.trading_phase import evaluate_live_gate

        return evaluate_live_gate(db)

    @app.get("/api/fitness/proof")
    def api_fitness_proof():
        from ..ops.capital_gate import evaluate_capital_gate

        return evaluate_capital_gate(db)

    @app.get("/api/historical_screen")
    def api_historical_screen(cleared_only: bool = False):
        from ..intelligence.historical_screen import list_historical_screen

        return {"results": list_historical_screen(db, cleared_only=cleared_only)}

    @app.get("/api/risk/slippage_bias")
    def api_slippage_bias():
        from ..ops.slippage_parity import running_bias

        return running_bias(db)

    @app.get("/api/risk/portfolio_greeks")
    def api_portfolio_greeks():
        from ..risk.portfolio_greeks import aggregate_portfolio_greeks, stress_book_loss_inr

        g = aggregate_portfolio_greeks(db)
        equity_row = db._conn.execute("SELECT IFNULL(SUM(delta),0) c FROM cash_ledger").fetchone()
        cash = float(equity_row["c"] or 0)
        pos_val = float(
            db._conn.execute(
                "SELECT IFNULL(SUM(qty*avg_price),0) v FROM positions WHERE qty>0"
            ).fetchone()["v"]
            or 0
        )
        equity = cash + pos_val
        return {
            "greeks": {
                "delta": g.delta,
                "gamma": g.gamma,
                "vega": g.vega,
                "theta": g.theta,
            },
            "stress": stress_book_loss_inr(db, equity),
        }

    @app.post("/api/budget/approve")
    def api_budget_approve(body: BudgetApproveBody, request: Request):
        require_admin(request)
        from ..ops.budget_gate import approve_budget_increase

        return approve_budget_increase(db, body.new_max)

    @app.post("/api/budget/reject")
    def api_budget_reject(request: Request):
        require_admin(request)
        from ..ops.budget_gate import reject_budget_increase

        return reject_budget_increase(db)

    @app.post("/api/slumber")
    def api_slumber(body: SlumberBody, request: Request):
        require_admin(request)
        from ..ops.slumber_mode import enter_slumber

        return enter_slumber(db, minutes=body.minutes, reason=body.reason)

    @app.post("/api/slumber/clear")
    def api_slumber_clear(request: Request):
        require_admin(request)
        from ..ops.slumber_mode import clear_slumber

        return clear_slumber(db)

    @app.get("/api/kite/holdings")
    def api_kite_holdings():
        from ..ingest.kite_holdings import fetch_holdings, real_holdings_value, sync_to_db

        sync_to_db(db)
        rows = db._conn.execute(
            "SELECT symbol, qty, avg_price, ltp, pnl, product, synced_ts FROM kite_holdings ORDER BY qty*ltp DESC"
        ).fetchall()
        return {
            "holdings": [dict(r) for r in rows],
            "total_value_inr": real_holdings_value(db),
            "synced_ts": rows[0]["synced_ts"] if rows else None,
            "live_fetch_count": len(fetch_holdings()),
        }

    @app.get("/api/strategy/discovery")
    def api_strategy_discovery():
        cur = db._conn.execute(
            """
            SELECT rule_id, symbol, win_rate, avg_return, sample_count, discovered_ts, promoted
            FROM strategy_discovery ORDER BY win_rate DESC, avg_return DESC LIMIT 20
            """
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/index/ohlc/{index_key}")
    def index_ohlc(index_key: str, period: str = "1d", interval: str = "5m"):
        from ..ingest.index_data import INDEX_MAP, fetch_index_ohlc

        key = index_key.lower()
        if key not in INDEX_MAP:
            raise HTTPException(status_code=404, detail=f"unknown index: {index_key}")
        return fetch_index_ohlc(key, period=period, interval=interval, db=db)

    @app.get("/api/stock/lookup/{symbol}")
    def stock_lookup(symbol: str):
        from ..ops.manual_trade import get_symbol_queue, lookup_symbol

        info = lookup_symbol(db, symbol)
        info["agent_queue"] = get_symbol_queue(db)
        return info

    @app.post("/api/stock/manual_buy")
    def stock_manual_buy(body: ManualBuyBody, request: Request):
        require_admin(request)
        from ..ops.manual_trade import execute_manual_paper_buy

        return execute_manual_paper_buy(db, body.symbol, qty=body.qty, reason=body.reason)

    @app.post("/api/stock/agent_queue")
    def stock_agent_queue(body: AgentQueueBody, request: Request):
        require_admin(request)
        from ..ops.manual_trade import queue_symbol_for_agent

        return queue_symbol_for_agent(db, body.symbol, note=body.note)

    @app.get("/api/status/board")
    def status_board():
        """Single endpoint for status bar + blockers — keeps dashboard resilient."""
        from ..ops.budget_gate import budget_status
        from ..ops.daily_pnl import portfolio_state
        from ..ops.healthchecks import check_token
        from ..ops.market_pulse import load_live_pulse
        from ..ops.agent_state import load_agent_status
        from ..ops.trading_phase import evaluate_live_gate

        st = portfolio_state(db)
        pulse = load_live_pulse(db)
        agent = load_agent_status(db)
        budget = budget_status(db)
        phase = evaluate_live_gate(db)
        last = agent.get("last_decision") or {}
        blockers: list[str] = []
        cash = float(st.get("cash", 0))
        if cash < 500:
            blockers.append(
                f"Paper cash only ₹{cash:.0f} — agent cannot buy (sell positions or add cash manually)"
            )
        remaining = float(budget.get("remaining_inr", 0))
        if remaining <= 0:
            pending = budget.get("pending_increase")
            exp = budget.get("pending_expires_in_sec")
            if pending and exp is not None:
                blockers.append(
                    f"Daily cap reached — approve ₹{pending.get('requested_max', 0):.0f}/day "
                    f"within {exp // 60}m or agent continues with current budget"
                )
            else:
                blockers.append(
                    "Daily budget cap reached — agent trades with remaining cash only until tomorrow"
                )
        if is_halted(db):
            blockers.append("Trading HALTED — click Resume")
        if not check_token(live=True):
            blockers.append("Kite token expired — login required for live data")
        last_action = None
        if last:
            last_action = f"{last.get('action')} {last.get('symbol', '')} ({last.get('reason', '')})".strip()

        return {
            "mode": os.getenv("TRADING_MODE", "paper"),
            "halted": is_halted(db),
            "kite_ok": check_token(live=True),
            "engine_live": pulse.get("engine_heartbeat_age_sec") is not None
            and pulse["engine_heartbeat_age_sec"] < 120,
            "engine_phase": agent.get("engine_phase"),
            "engine_24x7": agent.get("engine_24x7", True),
            "supervisor_state": agent.get("supervisor_state"),
            "supervisor_reason": agent.get("supervisor_reason"),
            "ws_live": pulse.get("ws_live", False),
            "cash": cash,
            "budget_used_pct": budget.get("budget_used_pct", 0),
            "budget_remaining": remaining,
            "budget_pending": budget.get("pending_increase"),
            "budget_pending_expires_sec": budget.get("pending_expires_in_sec"),
            "trading_phase": phase.get("phase"),
            "live_gate_eligible": phase.get("live_gate_eligible"),
            "paper_return_pct": (phase.get("paper_performance") or {}).get("return_pct"),
            "open_positions": pulse.get("open_positions", 0),
            "ticks_per_min": pulse.get("ticks_per_min", 0),
            "last_action": last_action,
            "blockers": blockers,
            "regime": (agent.get("context") or {}).get("regime"),
        }

    @app.get("/api/options/positions")
    def options_positions():
        cur = db._conn.execute(
            "SELECT symbol, underlying, strike, option_type, qty, avg_premium, last_premium, expiry, reason FROM option_positions"
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page():
        from .dashboard_template import render_dashboard

        return HTMLResponse(render_dashboard(DASHBOARD_CSS, strategy_count()))

    @app.get("/", response_class=HTMLResponse)
    def index():
        return RedirectResponse(url="/dashboard", status_code=302)

    return app


def main() -> None:
    import uvicorn
    uvicorn.run("src.api.dashboard:create_app", factory=True, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))


if __name__ == "__main__":
    main()

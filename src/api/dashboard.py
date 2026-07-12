"""FastAPI dashboard — login page, trading console, Kite OAuth callback."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ..auth.kite_auth import build_login_url
from ..db.database import DB, DBConfig
from ..ops.kill_switch import clear_halt, halt_status, is_halted, set_halt
from ..ops.daily_pnl import portfolio_state

_BASE_CSS = """
  :root {
    --bg: #0a0e14; --surface: #121820; --border: #1e2a3a;
    --text: #e8edf4; --muted: #8b9cb3; --accent: #3d8bfd;
    --green: #3ecf8e; --red: #f07178; --amber: #e6b450;
  }
  * { box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; margin: 0; background: var(--bg); color: var(--text); min-height: 100vh; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 1.5rem; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; }
  .btn { display: inline-block; background: var(--accent); color: #fff; border: none; padding: 0.65rem 1.25rem;
    border-radius: 8px; font-size: 0.95rem; font-weight: 600; cursor: pointer; text-decoration: none; }
  .btn:hover { filter: brightness(1.1); text-decoration: none; }
  .btn.danger { background: var(--red); }
  .btn.ghost { background: transparent; border: 1px solid var(--border); color: var(--text); }
  .badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 700; }
  .badge.ok { background: rgba(62,207,142,0.15); color: var(--green); }
  .badge.warn { background: rgba(230,180,80,0.15); color: var(--amber); }
  .badge.err { background: rgba(240,113,120,0.15); color: var(--red); }
  .nav { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; padding: 1rem 1.5rem;
    border-bottom: 1px solid var(--border); background: var(--surface); }
  .nav h1 { margin: 0; font-size: 1.15rem; }
  .grid3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; }
  .metric { font-size: 1.5rem; font-weight: 700; margin-top: 0.25rem; }
  .label { color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th, td { text-align: left; padding: 0.45rem 0.5rem; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; }
  .toast { position: fixed; bottom: 1.5rem; right: 1.5rem; padding: 0.75rem 1rem; border-radius: 8px;
    background: var(--surface); border: 1px solid var(--border); display: none; z-index: 99; }
  .toast.show { display: block; }
  .chart-box { height: 240px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
  .notice { color: var(--muted); font-size: 0.9rem; line-height: 1.5; }
  #appError { color: var(--red); margin: 1rem 0; }
"""


class HaltBody(BaseModel):
    reason: str = "manual"


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
    app = FastAPI(title="BharatQuant", version="0.4.0")
    db = DB(DBConfig(sqlite_path=os.getenv("SQLITE_PATH", "data/trading.db")))
    halt_secret = os.getenv("HALT_API_SECRET", "")
    api_key = os.getenv("KITE_API_KEY", "")

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
        return {
            **st,
            "mode": os.getenv("TRADING_MODE", "paper"),
            "login_url": build_login_url(api_key) if api_key else None,
            "redirect_url": os.getenv("KITE_REDIRECT_URL", ""),
        }

    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        login_url = build_login_url(api_key) if api_key else "#"
        redirect = os.getenv("KITE_REDIRECT_URL", "http://127.0.0.1:8080/kite/callback")
        mode = os.getenv("TRADING_MODE", "paper")
        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Login — BharatQuant</title><style>{_BASE_CSS}</style></head>
<body>
  <div class="wrap" style="max-width:520px;margin-top:3rem">
    <div class="card" style="text-align:center">
      <h1 style="margin:0 0 0.5rem">BharatQuant</h1>
      <p class="notice">Connect your Zerodha Kite account for market data and trading.</p>
    </div>
    <div class="card">
      <div class="label">Session</div>
      <p id="authStatus" style="margin:0.5rem 0 1rem">Checking…</p>
      <a id="kiteBtn" class="btn" href="{login_url}" style="width:100%;text-align:center">Connect Zerodha Kite</a>
      <p class="notice" style="margin-top:1rem">
        After login, Zerodha redirects to:<br><code>{redirect}</code>
      </p>
    </div>
    <div class="card">
      <div class="label">Trading mode</div>
      <p><span class="badge ok">{mode.upper()}</span> — paper mode uses simulated orders; no live money at risk.</p>
    </div>
    <div class="card">
      <div class="label">SEBI static IP (live orders)</div>
      <p class="notice">
        From <strong>April 1, 2026</strong>, Zerodha will <em>reject live API orders</em> not sent from a
        <strong>registered static IP</strong>. Login and data APIs work from your Mac; register a GCP static IP
        on your <a href="https://developers.kite.trade/" target="_blank">Kite developer profile</a> before going live.
      </p>
    </div>
    <p style="text-align:center"><a href="/dashboard">→ Open dashboard</a></p>
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
        return HTMLResponse(
            f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Login OK</title>
            <style>{_BASE_CSS}</style></head><body><div class="wrap" style="margin-top:3rem">
            <div class="card"><h2>Login successful</h2>
            <p>Kite access token saved. Engine will pick it up on next auth refresh.</p>
            <a class="btn" href="/dashboard">Open dashboard</a>
            <a class="btn ghost" href="/login" style="margin-left:0.5rem">Login page</a>
            </div></div></body></html>"""
        )

    @app.get("/api/overview")
    def overview():
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

    @app.get("/api/daily_tax_summary")
    def daily_tax_summary():
        from ..ops.daily_tax_summary import build_daily_summary

        return build_daily_summary(db)

    @app.get("/api/gift_gap")
    def gift_gap():
        cur = db._conn.execute(
            "SELECT payload_json FROM ingest_log WHERE event_type='GIFT_TICK' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if not cur:
            return {"change_pct": 0}
        try:
            p = json.loads(cur["payload_json"])
            return {"change_pct": p.get("change_pct", 0)}
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

        try:
            status = asyncio.run(fetch_nse_status())
        except Exception as exc:
            status = f"unknown ({exc})"
        return {
            "nse_status": status,
            "ist_note": "Agent screens on SESSION_PRE_OPEN; trades on TICK during market hours",
        }

    @app.post("/api/halt")
    def api_halt(body: HaltBody):
        """Dashboard halt — local paper mode (no secret required)."""
        if halt_secret:
            raise HTTPException(status_code=403, detail="use /internal/halt with X-Halt-Secret in production")
        set_halt(db, reason=body.reason)
        return halt_status(db)

    @app.post("/api/resume")
    def api_resume():
        if halt_secret:
            raise HTTPException(status_code=403, detail="use /internal/resume with X-Halt-Secret in production")
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

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page():
        return _DASHBOARD_HTML

    @app.get("/", response_class=HTMLResponse)
    def index():
        return RedirectResponse(url="/dashboard", status_code=302)

    return app


_DASHBOARD_HTML = f"""<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>BharatQuant Dashboard</title>
  <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
  <style>{_BASE_CSS}</style>
</head>
<body>
  <nav class="nav">
    <h1>BharatQuant</h1>
    <span id="modeBadge" class="badge ok">PAPER</span>
    <span id="tokenBadge" class="badge warn">…</span>
    <span id="haltBadge"></span>
    <span style="flex:1"></span>
    <a href="/login" class="btn ghost">Kite Login</a>
    <button type="button" class="btn danger" id="haltBtn">Halt trading</button>
    <button type="button" class="btn ghost" id="resumeBtn">Resume</button>
  </nav>
  <div class="wrap">
    <div id="appError"></div>
    <div class="card" style="border-color:var(--accent)">
      <h2 style="margin:0 0 0.75rem;font-size:1rem">🤖 Agent console <span class="label">autonomous — no manual triggers</span></h2>
      <div class="grid3">
        <div><div class="label">Regime</div><div class="metric" id="regime" style="font-size:1.1rem">—</div></div>
        <div><div class="label">NSE session</div><div class="metric" id="nseSession" style="font-size:1.1rem">—</div></div>
        <div><div class="label">Engine heartbeat</div><div class="metric" id="heartbeat" style="font-size:1.1rem">—</div></div>
      </div>
      <p id="agentNarrative" class="notice" style="margin:1rem 0"></p>
      <div class="grid3">
        <div class="card" style="margin:0">
          <div class="label">WS watchlist (bootstrap)</div>
          <table id="watchlist"><thead><tr><th>Symbol</th><th>Score</th></tr></thead><tbody></tbody></table>
        </div>
        <div class="card" style="margin:0">
          <div class="label">Last agent decision</div>
          <pre id="lastDecision" class="notice" style="margin:0;white-space:pre-wrap;font-size:0.8rem">—</pre>
        </div>
        <div class="card" style="margin:0">
          <div class="label">Ingest feeds (agent context)</div>
          <table id="ingest"><thead><tr><th>Source</th><th>Event</th></tr></thead><tbody></tbody></table>
        </div>
      </div>
      <p class="notice" style="margin-top:0.75rem">
        <strong>17 strategies</strong> run on every market event → AgentRouter fuses signals → risk/VaR/sector veto → paper broker.
        No cron. Sunday night = market closed → no ticks → no trades (expected).
      </p>
    </div>
    <div class="grid3">
      <div class="card"><div class="label">Cash</div><div class="metric" id="cash">—</div></div>
      <div class="card"><div class="label">Portfolio total</div><div class="metric" id="total">—</div></div>
      <div class="card"><div class="label">After-tax today</div><div class="metric" id="aftertax">—</div></div>
    </div>
    <div class="card">
      <div class="label">Equity curve</div>
      <div id="chart" class="chart-box" style="height:280px;margin-top:0.5rem"></div>
      <p id="chartNotice" class="notice" style="margin-top:0.5rem"></p>
    </div>
    <div class="grid3">
      <div class="card"><h3 style="margin-top:0">Positions</h3>
        <table id="pos"><thead><tr><th>Symbol</th><th>Qty</th><th>Avg</th><th>LTP</th></tr></thead><tbody></tbody></table>
      </div>
      <div class="card"><h3 style="margin-top:0">Allocation</h3>
        <table id="alloc"><thead><tr><th>Symbol</th><th>Wt</th><th>Qty</th></tr></thead><tbody></tbody></table>
      </div>
      <div class="card"><h3 style="margin-top:0">Recent signals</h3>
        <table id="sig"><thead><tr><th>Strategy</th><th>Symbol</th><th>Signal</th></tr></thead><tbody></tbody></table>
      </div>
    </div>
    <div class="card notice">
      <strong>Halt</strong> stops new paper/live orders (kill switch). <strong>Resume</strong> clears the halt.
      Engine reads this flag on every trade decision.
    </div>
  </div>
  <div id="toast" class="toast"></div>
  <script>
    function $(id) {{ return document.getElementById(id); }}
    function setText(id, text) {{
      const el = $(id);
      if (el) el.textContent = text;
    }}

    function toast(msg) {{
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 3500);
    }}

    async function loadAgent() {{
      const [agent, session] = await Promise.all([
        fetch('/api/agent/status').then(r => r.json()),
        fetch('/api/market/session').then(r => r.json()),
      ]);
      const ctx = agent.context || {{}};
      document.getElementById('regime').textContent = ctx.regime || 'NEUTRAL';
      document.getElementById('nseSession').textContent = session.nse_status || '—';
      const hb = agent.engine_heartbeat_ts;
      const hbEl = document.getElementById('heartbeat');
      if (hb) {{
        const age = Math.floor(Date.now()/1000) - hb;
        hbEl.textContent = age < 90 ? 'LIVE (' + age + 's ago)' : 'STALE (' + age + 's)';
        hbEl.style.color = age < 90 ? 'var(--green)' : 'var(--amber)';
      }} else {{
        hbEl.textContent = 'Engine not reporting';
        hbEl.style.color = 'var(--red)';
      }}
      const wl = agent.watchlist || [];
      document.querySelector('#watchlist tbody').innerHTML = wl.length
        ? wl.map(w => '<tr><td>'+w.symbol+'</td><td>'+Number(w.momentum_score).toFixed(2)+'</td></tr>').join('')
        : '<tr><td colspan="2">Runs at SESSION_PRE_OPEN</td></tr>';
      const ing = agent.ingest_feeds || [];
      document.querySelector('#ingest tbody').innerHTML = ing.length
        ? ing.map(i => '<tr><td>'+i.source+'</td><td>'+i.event_type+'</td></tr>').join('')
        : '<tr><td colspan="2">Feeds polling (FII, bulk, session…) — fills when APIs respond</td></tr>';
      const dec = agent.last_decision;
      document.getElementById('lastDecision').textContent = dec
        ? JSON.stringify(dec, null, 2)
        : 'No decisions yet — needs market TICK events during NSE hours';
      document.getElementById('agentNarrative').textContent =
        (agent.strategies_enabled || 17) + ' strategies armed · ' +
        (agent.signals_total||0) + ' signals · ' +
        (agent.shadow_total||0) + ' shadow · RL ' + (agent.rl_version||'ppo_v1') +
        (agent.rl_policy_exists ? ' ✓trained' : ' (collecting transitions)') +
        ' · supervisor ' + (agent.supervisor_state||'—') +
        (agent.supervisor_reason ? ' ('+agent.supervisor_reason+')' : '') +
        (agent.halted ? ' · HALTED' : '');
    }}

    async function loadMetrics() {{
      const o = await fetch('/api/overview').then(r => {{
        if (!r.ok) throw new Error('overview ' + r.status);
        return r.json();
      }});
      setText('cash', '₹' + Number(o.cash||0).toLocaleString('en-IN', {{maximumFractionDigits:0}}));
      setText('total', '₹' + Number(o.total_value||0).toLocaleString('en-IN', {{maximumFractionDigits:0}}));
      const hb = document.getElementById('haltBadge');
      if (hb) hb.innerHTML = o.halted
        ? '<span class="badge err">HALTED: ' + (o.reason||'manual') + '</span>'
        : '<span class="badge ok">TRADING ACTIVE</span>';

      const tax = await fetch('/api/daily_tax_summary').then(r => r.json());
      setText('aftertax', '₹' + Number(tax.net_after_tax_inr||0).toLocaleString('en-IN', {{maximumFractionDigits:0}}));

      const pos = await fetch('/api/positions').then(r => r.json());
      document.querySelector('#pos tbody').innerHTML = pos.length
        ? pos.map(p => '<tr><td>'+p.symbol+'</td><td>'+p.qty+'</td><td>'+Number(p.avg_price).toFixed(2)+'</td><td>'+Number(p.last_price).toFixed(2)+'</td></tr>').join('')
        : '<tr><td colspan="4" style="color:var(--muted)">No open positions</td></tr>';

      const sig = await fetch('/api/strategy_ledger').then(r => r.json());
      document.querySelector('#sig tbody').innerHTML = sig.length
        ? sig.slice(0,15).map(s => '<tr><td>'+s.strategy_id+'</td><td>'+s.symbol+'</td><td>'+(s.signal||'—')+'</td></tr>').join('')
        : '<tr><td colspan="3" style="color:var(--muted)">No signals yet (market closed or screening pending)</td></tr>';

      const alloc = await fetch('/api/allocation').then(r => r.json());
      document.querySelector('#alloc tbody').innerHTML = alloc.length
        ? alloc.map(a => '<tr><td>'+a.symbol+'</td><td>'+(a.weight*100).toFixed(1)+'%</td><td>'+a.target_qty+'</td></tr>').join('')
        : '<tr><td colspan="3" style="color:var(--muted)">Pre-open allocation runs on SESSION_PRE_OPEN</td></tr>';
    }}

    async function initCharts() {{
      if (typeof LightweightCharts === 'undefined') {{
        document.getElementById('chartNotice').textContent = 'Chart library blocked (CDN). Metrics above still work.';
        return;
      }}
      const opts = {{ layout: {{ background: {{ color: '#121820' }}, textColor: '#8b9cb3' }},
        grid: {{ vertLines: {{ color: '#1e2a3a' }}, horzLines: {{ color: '#1e2a3a' }} }} }};
      const el = document.getElementById('chart');
      const chart = LightweightCharts.createChart(el, opts);
      const series = chart.addAreaSeries({{ lineColor: '#3d8bfd', topColor: 'rgba(61,139,253,0.35)', bottomColor: 'rgba(61,139,253,0)' }});
      const hist = await fetch('/api/portfolio_history').then(r => r.json());
      if (hist.length) {{
        series.setData(hist.map(h => ({{ time: h.time, value: h.value }})));
      }} else {{
        document.getElementById('chartNotice').textContent = 'No portfolio history yet — builds after first session close.';
      }}
      new ResizeObserver(() => chart.applyOptions({{ width: el.clientWidth }})).observe(el);
    }}

    async function refreshAuth() {{
      const s = await fetch('/api/auth/status').then(r => r.json());
      document.getElementById('modeBadge').textContent = (s.mode||'paper').toUpperCase();
      document.getElementById('tokenBadge').className = 'badge ' + (s.valid ? 'ok' : 'err');
      document.getElementById('tokenBadge').textContent = s.valid ? 'KITE OK' : 'KITE LOGIN NEEDED';
    }}

    document.getElementById('haltBtn').addEventListener('click', async () => {{
      const r = await fetch('/api/halt', {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify({{reason:'dashboard'}}) }});
      const j = await r.json().catch(() => ({{}}));
      if (r.ok) {{ toast('Trading halted'); loadMetrics(); }}
      else toast('Halt failed: ' + (j.detail||r.status));
    }});

    document.getElementById('resumeBtn').addEventListener('click', async () => {{
      const r = await fetch('/api/resume', {{ method: 'POST' }});
      const j = await r.json().catch(() => ({{}}));
      if (r.ok) {{ toast('Trading resumed'); loadMetrics(); }}
      else toast('Resume failed: ' + (j.detail||r.status));
    }});

    (async function main() {{
      try {{
        await refreshAuth();
        await loadAgent();
        await loadMetrics();
        await initCharts();
        setInterval(loadMetrics, 15000);
        setInterval(loadAgent, 15000);
        setInterval(refreshAuth, 30000);
      }} catch (e) {{
        document.getElementById('appError').textContent = 'Dashboard error: ' + e.message;
      }}
    }})();
  </script>
</body></html>"""


def main() -> None:
    import uvicorn

    uvicorn.run("src.api.dashboard:create_app", factory=True, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))


if __name__ == "__main__":
    main()

"""FastAPI dashboard + TradingView Lightweight Charts."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..db.database import DB, DBConfig
from ..ops.kill_switch import clear_halt, halt_status, is_halted, set_halt
from ..ops.daily_pnl import portfolio_state

_STATIC = Path(__file__).with_name("static")


class HaltBody(BaseModel):
    reason: str = "manual"


def create_app() -> FastAPI:
    app = FastAPI(title="BharatQuant", version="0.3.0")
    db = DB(DBConfig(sqlite_path=os.getenv("SQLITE_PATH", "data/trading.db")))
    halt_secret = os.getenv("HALT_API_SECRET", "")

    def _check_halt_auth(x_halt_secret: str | None) -> None:
        if halt_secret and x_halt_secret != halt_secret:
            raise HTTPException(status_code=403, detail="invalid halt secret")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "mode": os.getenv("TRADING_MODE", "paper"),
            "halted": is_halted(db),
        }

    @app.get("/api/overview")
    def overview():
        st = portfolio_state(db)
        conn = db._conn
        buy = float(conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='BUY'").fetchone()[0])
        sell = float(conn.execute("SELECT IFNULL(SUM(amount),0) FROM trades WHERE side='SELL'").fetchone()[0])
        realized = sell - buy
        unrealized = float(
            conn.execute("SELECT IFNULL(SUM((last_price-avg_price)*qty),0) FROM positions").fetchone()[0]
        )
        return {
            "cash": st["cash"],
            "holdings_value": st["holdings_value"],
            "total_value": st["total_equity"],
            "realized_pnl": realized,
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
        import json

        cur = db._conn.execute(
            """
            SELECT payload_json FROM ingest_log
            WHERE event_type='GIFT_TICK' ORDER BY ts DESC LIMIT 1
            """
        ).fetchone()
        if not cur:
            return {"change_pct": 0, "gift_nifty_change_pct": 0}
        try:
            p = json.loads(cur["payload_json"])
            return {"change_pct": p.get("change_pct", 0), "gift_nifty_change_pct": p.get("change_pct", 0)}
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
        cur = db._conn.execute(
            "SELECT ts, total_value FROM portfolio_history ORDER BY ts ASC LIMIT 90"
        )
        return [{"time": int(r["ts"]), "value": float(r["total_value"])} for r in cur.fetchall()]

    @app.get("/api/allocation")
    def allocation():
        row = db._conn.execute("SELECT MAX(run_ts) AS m FROM portfolio_allocation").fetchone()
        if not row or row["m"] is None:
            return []
        cur = db._conn.execute(
            """
            SELECT symbol, weight, target_qty, target_rupees, last_price
            FROM portfolio_allocation WHERE run_ts=?
            ORDER BY weight DESC
            """,
            (row["m"],),
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/strategy_pnl")
    def strategy_pnl():
        cur = db._conn.execute(
            "SELECT strategy_id, realized_pnl, trade_count FROM strategy_pnl ORDER BY realized_pnl DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/shadow_trades")
    def shadow_trades():
        cur = db._conn.execute(
            "SELECT ts, strategy_id, symbol, action, confidence, price FROM shadow_trades ORDER BY ts DESC LIMIT 50"
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/ohlc/{symbol}")
    def ohlc(symbol: str, interval: str = "5m"):
        cur = db._conn.execute(
            """
            SELECT ts, open, high, low, close, volume FROM bar_log
            WHERE symbol=? AND interval=? ORDER BY ts ASC LIMIT 200
            """,
            (symbol, interval),
        )
        return [
            {
                "time": int(r["ts"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }
            for r in cur.fetchall()
        ]

    @app.get("/api/trade_markers")
    def trade_markers():
        cur = db._conn.execute(
            "SELECT ts, symbol, side, price FROM trades ORDER BY ts DESC LIMIT 100"
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/rolling_metrics")
    def rolling_metrics():
        cur = db._conn.execute(
            "SELECT ts, total_value FROM portfolio_history ORDER BY ts ASC LIMIT 60"
        )
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
            """
            SELECT ts, payload_json FROM ingest_log
            WHERE event_type='FII_DII_UPDATE' ORDER BY ts DESC LIMIT 30
            """
        )
        out = []
        import json

        for r in cur.fetchall():
            try:
                p = json.loads(r["payload_json"])
                out.append({"ts": r["ts"], "fii_net": p.get("fii_net", 0), "dii_net": p.get("dii_net", 0)})
            except json.JSONDecodeError:
                continue
        return list(reversed(out))

    @app.get("/api/ingest_latest")
    def ingest_latest():
        cur = db._conn.execute(
            """
            SELECT source, event_type, ts, execution_allowed
            FROM ingest_log ORDER BY ts DESC LIMIT 20
            """
        )
        return [dict(r) for r in cur.fetchall()]

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

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _DASHBOARD_HTML

    return app


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>BharatQuant</title>
  <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; background: #0d1117; color: #e6edf3; }
    header { padding: 1rem 1.5rem; border-bottom: 1px solid #30363d; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
    .chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: 1rem; }
    .chart-box { height: 260px; background: #161b22; border-radius: 8px; }
    #chart { height: 300px; margin: 1rem; background: #161b22; border-radius: 8px; }
    .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; padding: 1rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #30363d; }
    .card { background: #161b22; border-radius: 8px; padding: 1rem; }
    .metric { font-size: 1.4rem; font-weight: 600; }
    .halted { color: #f85149; font-weight: 700; }
    button { background: #238636; color: #fff; border: none; padding: 0.5rem 1rem; border-radius: 6px; cursor: pointer; }
    button.danger { background: #da3633; }
  </style>
</head>
<body>
  <header>
    <h1>BharatQuant</h1>
    <span id="haltBadge"></span>
    <span id="giftBadge"></span>
    <button class="danger" onclick="halt()">Halt</button>
    <button onclick="resume()">Resume</button>
  </header>
  <div class="grid">
    <div class="card"><div>Cash</div><div class="metric" id="cash">—</div></div>
    <div class="card"><div>Total</div><div class="metric" id="total">—</div></div>
    <div class="card"><div>After-tax today</div><div class="metric" id="aftertax">—</div></div>
  </div>
  <div id="chart"></div>
  <div class="chart-row">
    <div class="chart-box" id="fiiChart"></div>
    <div class="chart-box" id="giftChart"></div>
  </div>
  <div class="chart-row">
    <div class="chart-box" id="ohlcChart"></div>
    <div class="card"><h3>Strategy P&L</h3><table id="pnl"><tbody></tbody></table>
      <div>Sharpe <span id="sharpe">—</span> · Max DD <span id="maxdd">—</span></div>
    </div>
  </div>
  <div class="grid">
    <div class="card"><h3>Allocation</h3><table id="alloc"><thead><tr><th>Symbol</th><th>Wt</th><th>Qty</th></tr></thead><tbody></tbody></table></div>
    <div class="card"><h3>Positions</h3><table id="pos"><thead><tr><th>Symbol</th><th>Qty</th><th>Avg</th><th>LTP</th></tr></thead><tbody></tbody></table></div>
    <div class="card"><h3>Signals</h3><table id="sig"><thead><tr><th>Strategy</th><th>Symbol</th><th>Signal</th><th>Conf</th></tr></thead><tbody></tbody></table></div>
  </div>
  <script>
    const chartOpts = { layout: { background: { color: '#161b22' }, textColor: '#8b949e' },
      grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } } };
    async function load() {
      const o = await fetch('/api/overview').then(r => r.json());
      document.getElementById('cash').textContent = '₹' + o.cash.toFixed(0);
      document.getElementById('total').textContent = '₹' + o.total_value.toFixed(0);
      document.getElementById('haltBadge').innerHTML = o.halted
        ? '<span class="halted">HALTED: ' + (o.reason||'') + '</span>' : '<span>ACTIVE</span>';
      const tax = await fetch('/api/daily_tax_summary').then(r => r.json());
      document.getElementById('aftertax').textContent = '₹' + (tax.net_after_tax_inr||0).toFixed(0);
      const gift = await fetch('/api/gift_gap').then(r => r.json());
      document.getElementById('giftBadge').textContent = 'GIFT gap: ' + (gift.change_pct||0).toFixed(2) + '%';
      const pos = await fetch('/api/positions').then(r => r.json());
      document.querySelector('#pos tbody').innerHTML = pos.map(p =>
        `<tr><td>${p.symbol}</td><td>${p.qty}</td><td>${p.avg_price.toFixed(2)}</td><td>${p.last_price.toFixed(2)}</td></tr>`).join('');
      const sig = await fetch('/api/strategy_ledger').then(r => r.json());
      document.querySelector('#sig tbody').innerHTML = sig.map(s =>
        `<tr><td>${s.strategy_id}</td><td>${s.symbol}</td><td>${s.signal||''}</td><td>${(s.confidence||0).toFixed(2)}</td></tr>`).join('');
      const alloc = await fetch('/api/allocation').then(r => r.json());
      document.querySelector('#alloc tbody').innerHTML = alloc.map(a =>
        `<tr><td>${a.symbol}</td><td>${(a.weight*100).toFixed(1)}%</td><td>${a.target_qty}</td></tr>`).join('');
      const m = await fetch('/api/rolling_metrics').then(r => r.json());
      document.getElementById('sharpe').textContent = (m.sharpe||0).toFixed(2);
      document.getElementById('maxdd').textContent = (m.max_drawdown_pct||0).toFixed(1) + '%';
      const pnl = await fetch('/api/strategy_pnl').then(r => r.json());
      document.querySelector('#pnl tbody').innerHTML = pnl.map(p =>
        `<tr><td>${p.strategy_id}</td><td>₹${(p.realized_pnl||0).toFixed(0)}</td></tr>`).join('');
    }
    async function halt() {
      await fetch('/internal/halt', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({reason:'dashboard'})});
      load();
    }
    async function resume() {
      await fetch('/internal/resume', {method:'POST'});
      load();
    }
    const chart = LightweightCharts.createChart(document.getElementById('chart'), chartOpts);
    const series = chart.addAreaSeries({ lineColor: '#58a6ff', topColor: 'rgba(88,166,255,0.4)', bottomColor: 'rgba(88,166,255,0)' });
    const hist = await fetch('/api/portfolio_history').then(r => r.json());
    if (hist.length) series.setData(hist.map(h => ({ time: h.time, value: h.value })));
    const fiiChart = LightweightCharts.createChart(document.getElementById('fiiChart'), chartOpts);
    const fiiLine = fiiChart.addLineSeries({ color: '#58a6ff', title: 'FII' });
    const diiLine = fiiChart.addLineSeries({ color: '#f0883e', title: 'DII' });
    const fii = await fetch('/api/fii_series').then(r => r.json());
    if (fii.length) {
      fiiLine.setData(fii.map(x => ({ time: x.ts, value: x.fii_net })));
      diiLine.setData(fii.map(x => ({ time: x.ts, value: x.dii_net })));
    }
    const giftChart = LightweightCharts.createChart(document.getElementById('giftChart'), chartOpts);
    const giftLine = giftChart.addHistogramSeries({ color: '#3fb950' });
    const g = await fetch('/api/gift_gap').then(r => r.json());
    giftLine.setData([{ time: Math.floor(Date.now()/1000), value: g.change_pct||0, color: (g.change_pct||0)>=0?'#3fb950':'#f85149' }]);
    const ohlcEl = document.getElementById('ohlcChart');
    const oChart = LightweightCharts.createChart(ohlcEl, chartOpts);
    const candle = oChart.addCandlestickSeries();
    const sym = (await fetch('/api/positions').then(r=>r.json()))[0]?.symbol || 'INFY';
    const bars = await fetch('/api/ohlc/' + sym + '?interval=5m').then(r => r.json());
    if (bars.length) candle.setData(bars);
    const markers = await fetch('/api/trade_markers').then(r => r.json());
    if (markers.length && bars.length) {
      candle.setMarkers(markers.slice(0,20).map(t => ({
        time: t.ts, position: t.side==='BUY'?'belowBar':'aboveBar',
        color: t.side==='BUY'?'#3fb950':'#f85149', shape: t.side==='BUY'?'arrowUp':'arrowDown',
        text: t.side,
      })));
    }
    load();
    setInterval(load, 15000);
  </script>
</body>
</html>"""


def main() -> None:
    import uvicorn

    uvicorn.run("src.api.dashboard:create_app", factory=True, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))


if __name__ == "__main__":
    main()

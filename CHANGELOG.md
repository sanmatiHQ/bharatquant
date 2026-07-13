# BharatQuant Changelog

## 2026-07-13 — Dashboard v2 (public + owner auth)

### UX overhaul
- **Mobile-first** single-page layout — KPIs, live activity stream, agent decision hero, charts, positions
- **`GET /api/feed/live`** — one poll every 3s (no empty hidden tabs)
- Real-time activity: trades, signals, decisions with timestamps

### Auth model
- **`/dashboard`** — **public read-only** (anyone can watch agent + PnL)
- **`/admin`** — single owner login (`DASHBOARD_ADMIN_USER` / `DASHBOARD_ADMIN_PASSWORD`)
- POST actions (halt, budget approve, paper buy) require owner session cookie
- Cloud: credentials synced via `gcp_sync_secrets.sh`

### Broker latency (research)
- Zerodha Kite WebSocket remains primary feed
- [Fyers API v3](https://myapi.fyers.in/docsv3) noted for lower-latency alternative — broker abstraction deferred until paper gate clears

## 2026-07-13 — Cloud deploy + 15m budget timeout + paper→live gate

### Budget approval timeout
- **`BUDGET_APPROVAL_TIMEOUT_SEC=900`** — if user does not approve within 15 minutes, pending request expires
- Agent **does not wait** for more funds — trades with remaining daily budget/cash only
- Dashboard shows countdown on pending approval card

### Trading lifecycle (`src/ops/trading_phase.py`)
- **Phase 1 `paper_learn`** (default) — real Kite data, paper execution, RL + discovery
- **Phase 2 `live_deploy`** — after paper return ≥ `LIVE_GATE_MIN_PAPER_RETURN_PCT` (5%) and ≥20 trades in 30d, set `TRADING_MODE=live` for **₹1,500–₹2,000/day** real Zerodha capital
- Engine blocks accidental `TRADING_MODE=live` before gate clears

### GCP production
- `deploy/bharatquant.env.production` — `ENGINE_24X7`, ₹1500–2000 daily range, 15m timeout
- `gcp_sync_secrets.sh` — restarts supervisor after secret sync
- VM: `bharatquant-engine` on your GCP project — independent of Mac

## 2026-07-13 — Open source release

- Repo published as **public** under Apache 2.0
- Secrets audit: `bash scripts/audit_secrets.sh`
- Production hostnames / project IDs replaced with placeholders in tracked files
- `deploy/Caddyfile` gitignored — use `deploy/Caddyfile.example` + `setup_https.sh`

## 2026-07-13 — 24×7 agent (observe + learn always on)

### Supervisor
- **`ENGINE_24X7=true`** (default) — engine + dashboard never stop; weekends/nights run **learn_only** mode
- Auto-restart engine on stale heartbeat (90s) or crash; dashboard restarted every poll if down
- **`scripts/install_launch_agent.sh`** — macOS LaunchAgent keeps supervisor alive across reboots
- Status bar shows **24×7 LEARN**, **OFF-HOURS** vs **SESSION**, supervisor reason

### Engine
- **`engine_phase`** persisted each heartbeat: `active_trading` (9:25–15:30 IST weekdays) vs `learn_only`
- Off-hours: ingest (GIFT, FII, macro), strategy discovery, RL buffer, bandit weights still run

## 2026-07-13 — Budget discipline, real holdings, UI, strategy expansion

### Budget & paper cash (user mandate)
- **Removed auto top-up** — `_seed_paper_cash` seeds once only; no silent refill to `PAPER_STARTING_CASH`
- **Hard daily deploy cap** — `DAILY_INVESTMENT_MIN/MAX` default **₹1,000–₹2,000** (`config.yaml`)
- **`src/ops/budget_gate.py`** — tracks `deployed_today_inr`, enforces cap at execution time
- **User approval flow** — when agent needs more budget, it creates a pending request; dashboard **Approve / Reject** buttons call `/api/budget/approve` and `/api/budget/reject`

### Real Zerodha portfolio
- **`src/ingest/kite_holdings.py`** — syncs `kite.holdings()` + `kite.positions()` every 15 min
- **`kite_holdings` table** — dashboard shows real holdings with green/red PnL
- **Agent awareness** — execution skips paper CNC buys on symbols you already hold in real life

### Dashboard UX
- **Hero market chart** at top (Nifty 50 / 100 / broad) — always visible
- **Green profit / red loss** — realized, unrealized, return today, positions, strategy PnL, real holdings
- **Real holdings panel** + **strategy discovery** table (bar_log mining)
- **Budget approval card** when agent requests limit increase

### Strategies (30 built-in + custom YAML)
Previous session added 11 advanced strategies (`advanced_quant.py`). This session adds:
- **`sector_rotation`** — relative strength within `symbol_sectors`
- **`options_greeks`** — VIX-triggered hedges + IV premium fade
- **Enhanced `pairs_stat_arb`** — live spread z-score + volume confirm; `PAIRS_ARB_LIST` env (e.g. `RELIANCE/ONGC,SBIN/ICICIBANK`)
- **`src/intelligence/strategy_discovery.py`** — hourly mines `bar_log` for rule candidates → `strategy_discovery` table

### Cross-market feeds (prior session, documented)
- GIFT Nifty via NSE `marketStatus.giftnifty` (not yfinance)
- FII/DII via NSE `fiidiiTradeReact`
- US futures, crude, USD/INR via Kite + Yahoo chart API

### India algo community insights (r/IndiaAlgoTrading / Zerodha Q&A)
Incorporated patterns discussed in Indian retail algo circles:
- **ORB + VWAP reset at 9:15** — already in opening_range / vwap strategies
- **Cost-edge gate** before entry — brokerage must not eat expected move
- **Paper 2–3 months before live** — `TRADING_MODE=paper` default
- **SEBI Algo-ID + static IP** — documented in login page for Apr 2026 live orders
- **Backtest-live parity** — same execution engine for paper; discovery mines live `bar_log`

### Config reference
```env
DAILY_INVESTMENT_MIN=1000
DAILY_INVESTMENT_MAX=2000
MAX_RUPEES_PER_TRADE=2000
PAPER_STARTING_CASH=5000   # seed once only
PAIRS_ARB_LIST=RELIANCE/ONGC,SBIN/ICICIBANK
```

### API additions
| Endpoint | Purpose |
|----------|---------|
| `GET /api/budget` | Daily budget status + pending approval |
| `POST /api/budget/approve` | User raises approved daily max |
| `POST /api/budget/reject` | Dismiss agent budget request |
| `GET /api/kite/holdings` | Real Zerodha holdings sync |
| `GET /api/strategy/discovery` | Mined rule candidates from bar_log |

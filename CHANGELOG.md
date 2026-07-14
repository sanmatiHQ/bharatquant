# BharatQuant Changelog

## 2026-07-14 — Intelligence honesty + risk-adjusted learning (deployed VM)

### Audit fixes (items 0–10) — stop measuring fake edge
- **Paper slippage** — `PaperBroker` delegates to `CostEngine` only (BUY above LTP, SELL below)
- **Regime classifier** — rolling `index_returns` deque + bar_log fallback; FII nudges adjacent regimes only
- **Kelly sizing** — per-strategy Bayesian stats (`strategy_stats.py`); removed silent ×0.02; `KELLY_SAFETY_SCALAR`
- **Bandit** — Thompson sampling from realized win/loss (not self-reported confidence)
- **RL gym** — net-of-cost rewards via `CostEngine`; hold steps pass net unrealized
- **Shadow gate** — requires ≥500 bars + ≥3 symbols; no auto-pass on thin/neutral history
- **RL inference** — `RLAgent` loads `sb3_ppo.zip` when present; numpy export is fallback only
- **Strategy correlation** — disable redundant pairs (>0.7); binomial promotion gate (p<0.05)
- **Cost-edge** — removed hardcoded `_STRATEGY_EDGE_PCT`; measured `expected_move_pct_for_strategy()`
- **Portfolio beta cap** — `portfolio_beta.can_add_beta_exposure()` in `risk_veto`
- **RBI calendar** — published MPC dates 2025/2026; Wilder RSI in strategy discovery

### Risk-adjusted fitness — single learning objective
- **`risk_metrics.py`** — downside deviation, Sortino, Calmar composite (not raw PnL)
- **RL reward** — Sortino-shaped: `net_return − λ·downside_deviation`
- **Adaptive Kelly** — fraction shrinks when win-rate variance is high
- **Shadow/promotion** — Calmar + Sortino composite gates (RL, discovery, strategy_lab)
- **Credit assignment** — all fuse competitors logged to `shadow_trades`
- **Bandit diversity cap** — `BANDIT_MAX_WEIGHT=0.40`
- **Regime switching** — vol/return shock trigger + 3-bar persistence dampener
- **Strategy lifecycle** — candidacy → probation (10%) → full → auto-demotion

### Deploy
- Pre-deploy: 161 pytest passed; post-deploy gate ALL PASS on production VM
- Dashboard live on configured public host

## 2026-07-14 — Deploy hardening (startup regression prevention)

- **Pre-deploy smoke** (`scripts/pre_deploy_smoke.sh`) — pytest + engine boot contract; blocks broken deploys
- **Post-deploy gate** (`scripts/post_deploy_gate.sh`) — HTTPS/local health, single engine+dashboard PID, heartbeat, kite auth
- **Token clobber fix** — `gcp_sync_secrets.sh` preserves VM OAuth token unless `SYNC_KITE_TOKEN=1` + live validation
- **Supervisor orphan fix** — `_bootstrap_stack()` kills stale processes before binding :8080
- **Kite hot-reload** — `kite_token_watcher` restarts feed ~10s after OAuth without full engine restart
- **Engine boot fix** — `persist_engine_phase(db)` arity corrected

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

## 2026-07-13 — Open source completion

- `CONTRIBUTING.md`, `SECURITY.md`, `.github/` CI + templates
- Full `.env.example`, `scrub_git_history.sh`, `test_open_source_hygiene.py`
- SYSTEM_TRACKER Layer 12 (BQ-OS1..OS8)

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

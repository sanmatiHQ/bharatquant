here’s the final Cursor build manifest — the authoritative contract for agents to generate the entire base system today, including RL (observer-mode) versioning from day one. No ambiguity, no rework.

⸻

Repo layout (single source of truth)

zerodha-momo-rl/
  README.md
  requirements.txt
  .env.example
  config.yaml
  data/
    universe_nifty200.csv
  logs/
    .gitkeep
  models/
    rl/
      baseline/                # placeholder for “no-RL” controller
      ppo_v1/                  # versioned RL weights/config (observer until enabled)
  src/
    __init__.py
    utils/
      timebox.py               # IST-aware time helpers
      rate_limit.py            # token-bucket throttle
      backoff.py               # retry wrappers
      logging_setup.py         # structured JSON logging
    auth/
      kite_auth.py             # token refresh (callback server + exchange)
    data/
      kite_data_feed.py        # LTP + OHLC; Zerodha-only
    db/
      database.py              # SQLite schema + accessors
      migrations.sql           # schema bootstrap
    features/
      indicators.py            # RSI, returns, MAs, volatility
      feature_store.py         # rolling feature calc/cache
    screening/
      momentum_screener.py     # 1M/3M + RSI + MA align + filters
      advanced_screener.py     # (optional) patterns; hooks only
    costs/
      cost_engine.py           # brokerage, taxes, infra; FIFO lots
    risk/
      risk_engine.py           # SL %, daily loss gate, caps
    exec/
      trade_executor.py        # cash-add, sizing, paper fills
      paper_broker.py          # deterministic fills + slippage
    rl/
      rl_buffer.py             # replay buffer (SQLite)
      rl_agent.py              # interface; PPO/“baseline” controller
      rl_trainer.py            # offline/nightly trainer (stub)
      reward.py                # after-cost, after-tax reward
    api/
      app.py                   # Flask APIs
    ops/
      scheduler.py             # 07:35 / 09:20 jobs
      start_system.sh          # dashboard + scheduler
      morning_auth.sh          # open login + run callback
      healthchecks.py          # sanity probes
  tests/
    test_screener.py
    test_cost_engine.py
    test_database.py
    test_executor.py

Design anchors (from your guide): Zerodha-only data, token @~07:35 IST, strategy run 09:20 IST, NIFTY200 default, Flask dashboard endpoints, SQLite schema.  ￼  ￼

⸻

Environment + tooling

requirements.txt

Pin stable libs (Cursor will install):

Flask==3.0.0
pytz==2024.1
python-dateutil==2.9.0
PyYAML==6.0.2
pandas==2.2.2
numpy==2.0.0
requests==2.32.3
kiteconnect==5.0.0
APScheduler==3.10.4

.env.example

KITE_API_KEY=
KITE_API_SECRET=
KITE_REDIRECT_URL=http://localhost:8080/kite/callback
KITE_ACCESS_TOKEN_FILE=.kite_token.json
TZ=Asia/Kolkata


⸻

Config schema — config.yaml

app:
  tz: "Asia/Kolkata"
  logs_dir: "logs"

zerodha:
  api_key: "${KITE_API_KEY}"
  api_secret: "${KITE_API_SECRET}"
  redirect_url: "${KITE_REDIRECT_URL}"
  post_reset_time_ist: "07:35"   # refresh after reset

trading:
  mode: "paper"                  # "paper" | "live" later
  universe_csv: "data/universe_nifty200.csv"
  run_time_ist: "09:20"
  daily_investment: 1000         # ₹1k/day
  min_score: 0.65
  slippage_bps: 4                # haircuts in paper fills
  max_positions: 20

filters:
  min_market_cap_cr: 2000        # optional
  min_avg_volume_20d: 300000     # optional

risk:
  stop_loss_percent: 4.0
  max_daily_loss_percent: 2.0

storage:
  sqlite_path: "data/trading.db"

rl:
  active_version: "baseline"     # "baseline" means RL observe-only
  model_dir: "models/rl"
  algorithm: "ppo"
  gamma: 0.99
  lr: 0.0003
  reward_drawdown_penalty: 0.5
  train_offline: true

(These reflect your project guide’s timing, universe, and automation contracts.  ￼)

⸻

Database schema — src/db/migrations.sql

Execute once at startup if tables missing (Cursor agents: ensure idempotent init).

PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);

CREATE TABLE IF NOT EXISTS cash_ledger (
  ts INTEGER NOT NULL,
  delta REAL NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT CHECK(side IN ('BUY','SELL')) NOT NULL,
  qty INTEGER NOT NULL,
  price REAL NOT NULL,
  amount REAL NOT NULL,
  reason TEXT,
  fees REAL DEFAULT 0,
  stcg_ltcg TEXT CHECK(stcg_ltcg IN ('STCG','LTCG','NA')) DEFAULT 'NA'
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts);

CREATE TABLE IF NOT EXISTS positions (
  symbol TEXT PRIMARY KEY,
  qty INTEGER NOT NULL,
  avg_price REAL NOT NULL,
  last_price REAL NOT NULL,
  open_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS screening_results (
  run_ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  momentum_score REAL NOT NULL,
  r1m REAL, r3m REAL, rsi REAL, ma_align INTEGER,
  PRIMARY KEY (run_ts, symbol)
);

CREATE TABLE IF NOT EXISTS portfolio_history (
  ts INTEGER PRIMARY KEY,
  cash REAL NOT NULL,
  holdings_value REAL NOT NULL,
  total_value REAL NOT NULL,
  realized_pnl REAL NOT NULL,
  unrealized_pnl REAL NOT NULL,
  max_drawdown REAL DEFAULT 0
);

-- RL observer buffer
CREATE TABLE IF NOT EXISTS rl_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  version TEXT NOT NULL,
  symbol TEXT NOT NULL,
  state BLOB NOT NULL,
  action TEXT NOT NULL,
  reward REAL NOT NULL,
  next_state BLOB NOT NULL,
  done INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rl_versions (
  version TEXT PRIMARY KEY,
  algo TEXT NOT NULL,
  status TEXT CHECK(status IN ('active','staging','retired')) NOT NULL,
  created_ts INTEGER NOT NULL,
  notes TEXT
);

(The tables align with your guide’s trades/positions/screening/portfolio history definition.  ￼)

⸻

Module-by-module contract

src/utils/timebox.py
	•	Purpose: IST-aware now/next-run helpers; parse HH:MM; is_market_open.
	•	Key fns: now_ist(), today_ist(), parse_hhmm(s) -> (h,m), next_time_today(hh, mm).

src/utils/rate_limit.py
	•	Purpose: Token-bucket limiter for REST bursts.
	•	API: RateLimiter(max_per_sec=3, max_per_min=180).allow() returns bool; internal deque cleanup.

src/utils/backoff.py
	•	Purpose: Retry with jittered exponential backoff.
	•	API: @retry(max_tries=5, base=0.2, cap=2.5, jitter=True) decorator.

src/utils/logging_setup.py
	•	Purpose: JSON logger with module name; file + stdout handlers.
	•	API: get_logger(name) -> logging.Logger.

⸻

src/auth/kite_auth.py
	•	Purpose: Automate Zerodha request_token → access_token exchange (local callback server).
	•	CLI: python -m src.auth.kite_auth --auto
	•	Flow:
	1.	Start local HTTP server on redirect_url (from .env/config).
	2.	Open login URL https://api.kite.trade/connect/login?api_key=....
	3.	On callback, extract request_token, compute checksum sha256(api_key + request_token + api_secret), POST form-encoded to /session/token. Store access_token in KITE_ACCESS_TOKEN_FILE.
	•	Outputs: writes token JSON, logs success/failure.
	•	Notes: Use form-encoded POST; not JSON.

Schedule contract: refresh daily ~07:35 IST, as per your design.  ￼

⸻

src/data/kite_data_feed.py
	•	Purpose: Single source for LTP and historical OHLC (no yfinance).
	•	API:
	•	ltp(instruments: list[str]) -> dict[str, float] (e.g., "NSE:INFY": 1550.2)
	•	historical(instrument_token: int, start, end, interval="day") -> pd.DataFrame
	•	Constraints: internal rate limiter (≈3 req/sec), retries/backoff, error classification.
	•	Config: reads API key + access token; raises if token missing.

(“Zerodha-only” and rate-limit posture reflect your guide.  ￼)

⸻

src/db/database.py
	•	Purpose: Bootstrap migrations.sql, typed CRUD helpers, and transactions.
	•	API: DB(path).add_cash(...), record_trade(...), upsert_position(...), record_screen(...), snapshot_portfolio(...).
	•	Behavior: WAL mode; all writes in short transactions; row_factory=sqlite3.Row.

⸻

src/features/indicators.py
	•	Purpose: RSI(14); rolling returns; MA(20/50/200); realized volatility.
	•	API: rsi(series), pct_ret(series, lookback), ma_align(close) -> 0/1.

src/features/feature_store.py
	•	Purpose: Build per-symbol factor vector from OHLC; caches intermediate results in memory; optional on-disk parquet later.
	•	API: compute_features(hist_df) -> dict.

⸻

src/screening/momentum_screener.py
	•	Purpose: Score & rank universe with your factors (1M/3M, RSI, MA align) and filters (mcap, avg volume).
	•	API: run() -> pd.DataFrame with columns: symbol, score, r1m, r3m, rsi, ma_align; persists top-N to screening_results.
	•	Config: trading.min_score, filters.*, universe_csv.
	•	Rate limit: uses small worker pool (2) and sleeps (≈0.4s) when looping many symbols, per guide.  ￼

src/screening/advanced_screener.py (optional)
	•	Purpose: Hook points for NSE-Scanner / PKScreener flags to boost score.
	•	Contract: Pure optional; no yfinance.  ￼

⸻

src/costs/cost_engine.py
	•	Purpose: Compute per-trade total costs and tax bucket (STCG/LTCG) with FIFO lots; amortize infra/API.
	•	API: compute_trade_costs(symbol, qty, price, side, ts) -> fees_float, classify_tax(hold_days) -> 'STCG'|'LTCG'|'NA'.
	•	Daily: aggregate to update portfolio_history with after-cost, after-tax P&L.

(Your requirements: “net after taxes + fees + infra,” baked-in.)

⸻

src/risk/risk_engine.py
	•	Purpose: Hard stop-loss %, daily loss gate, max positions; cooldown windows.
	•	API: can_open_new(state) -> (bool, reason), should_exit(symbol_state) -> bool.

⸻

src/exec/paper_broker.py
	•	Purpose: Deterministic paper fills at current LTP minus slippage haircut (bps).
	•	API: buy(symbol, qty) -> exec_px, sell(...).
	•	Writes: trades table, positions, cash_ledger.

src/exec/trade_executor.py
	•	Purpose: 09:20 control block: add ₹1k cash, read ranked list, apply risk gates, size to whole shares, place paper trades, update DB, write portfolio snapshot.
	•	Inputs: screener output; risk gate; LTPs; costs engine.
	•	Outputs: trades, positions, portfolio_history; logs.

(“Buy at 09:20 IST, cash accumulation ₹1k/day, whole shares” per your doc.  ￼)

⸻

RL subsystem (wired from day one, observer mode)

src/rl/rl_buffer.py
	•	Purpose: Store (state, action, reward, next_state, done) transitions to SQLite rl_transitions.
	•	API: push(version, symbol, s, a, r, s2, done), sample(n) -> list.

src/rl/reward.py
	•	Purpose: Reward = after-cost, after-tax daily return minus drawdown penalty (reward_drawdown_penalty).
	•	API: compute_reward(trade_or_day_snapshot) -> float.

src/rl/rl_agent.py
	•	Purpose: Versioned controller.
	•	Modes:
	•	"baseline" → returns deterministic action based on baseline score (no learning).
	•	"ppo_v1" → loads policy from models/rl/ppo_v1/; if untrained, acts conservative and logs obs only.
	•	API: act(state, symbol) -> action, load(version), is_learning_enabled() (false by default).

src/rl/rl_trainer.py (stub for now)
	•	Purpose: Offline/nightly trainer process to learn from rl_transitions and write weights to version dir.
	•	CLI: python -m src.rl.rl_trainer --version ppo_v1 --epochs 5 (no-op stub today with TODOs).

Versioning
	•	Table rl_versions tracks status; config key rl.active_version selects which to load.

⸻

src/api/app.py (Flask)
	•	Endpoints (as per your guide):
	•	GET /api/overview — portfolio, P&L, stats
	•	GET /api/positions — open paper positions
	•	GET /api/trades — recent trades
	•	GET /api/screening — latest screening results
	•	GET /api/market-updates — (stub) top gainers/losers via Kite
	•	GET /api/stock-search?q= — instrument lookup + 1M/3M/RSI
	•	GET /api/logs — last 100 lines of logs/trading.log
(Endpoints match your plan.  ￼)
	•	Standards: JSON only; 200ms median; CORS off (local).

⸻

src/ops/scheduler.py
	•	Purpose: Two cron-like jobs with APScheduler:
	•	07:35 IST — token refresh (auth.kite_auth)
	•	09:20 IST — daily run: screen → risk → execute → snapshot
	•	Health: on each run, write to logs/scheduler.log.

(Your automation cadence.  ￼)

src/ops/start_system.sh
	•	Start Flask on :8080, then start scheduler in background; set PYTHONUNBUFFERED=1.

src/ops/morning_auth.sh
	•	Open browser to login URL and run callback server for token exchange.

src/ops/healthchecks.py
	•	check_token(), check_db(), check_endpoints(); returns machine-readable status.

⸻

Logging
	•	Files: logs/trading.log, logs/scheduler.log, logs/dashboard.log. (As defined in your guide.  ￼)
	•	Format: JSON lines with ts, level, module, msg, context.

⸻

Tests (minimal but surgical)
	•	test_screener.py: deterministic fixture → ranked output length & ordering.
	•	test_cost_engine.py: fee/tax calculation against known cases.
	•	test_database.py: migrations + round-trip CRUD.
	•	test_executor.py: simulate one 09:20 run → positions/cash/trades consistent.

⸻

Cursor instructions (paste this block to the agent)

Task: Generate the codebase exactly to the manifest below. Follow file paths, function names, and APIs. Include type hints and docstrings. Use pandas/numpy where stated. Do not invent endpoints, flags, or filenames. Respect IST timing.

Order of generation (to avoid circulars):
	1.	requirements.txt, .env.example, config.yaml, README.md
	2.	src/utils/* (timebox, rate_limit, backoff, logging_setup)
	3.	src/db/migrations.sql, src/db/database.py
	4.	src/auth/kite_auth.py
	5.	src/data/kite_data_feed.py
	6.	src/features/*
	7.	src/costs/cost_engine.py
	8.	src/risk/risk_engine.py
	9.	src/screening/momentum_screener.py (+ advanced_screener.py as stub)
	10.	src/exec/paper_broker.py, src/exec/trade_executor.py
	11.	src/rl/* (buffer, reward, rl_agent baseline/ppo stubs, rl_trainer stub)
	12.	src/api/app.py
	13.	src/ops/* (scheduler, scripts, healthchecks)
	14.	tests/*
	15.	data/universe_nifty200.csv (header + 3 sample rows; user will replace)

Coding standards:
	•	Python 3.11+, PEP8, mypy-friendly typing.
	•	No global state; inject config/DB/loggers.
	•	All network calls wrapped with retry + RateLimiter.
	•	Flask blueprint under /api; return application/json only.
	•	Every write-path logs a compact structured event.

Acceptance criteria for “Today Done”:
	•	python -m src.auth.kite_auth --auto persists a token file (manual browser login step acceptable).
	•	python -m src.ops.scheduler runs both jobs and writes to logs (mock token ok if market closed).
	•	python -m src.api.app serves endpoints responding with stubbed or live data.
	•	One dry run (using sample OHLC fixtures if markets closed) writes rows into screening_results, trades, positions, and portfolio_history.

⸻

Runbook (paper)
	•	07:35 IST: kite_auth → KITE_ACCESS_TOKEN_FILE.
	•	09:20 IST: trade_executor sequence:
	1.	add ₹1,000 → cash_ledger
	2.	read universe → features → momentum_screener
	3.	risk gates → size whole shares
	4.	paper_broker fills @ LTP with slippage bps
	5.	compute fees/taxes → record in trades
	6.	positions and portfolio_history snapshot
	7.	RL observer: push (s,a,r,s′) into rl_transitions for the active version (likely “baseline”)

⸻

Switches you control (no code change)
	•	Enable RL control later: set rl.active_version: "ppo_v1" (once weights exist and pass paper A/B).
	•	Expand universe: replace data/universe_nifty200.csv.
	•	Tighten risk: edit risk.max_daily_loss_percent and trading.max_positions.
	•	Slippage realism: raise trading.slippage_bps.

⸻

Notes on your guide alignment
	•	Zerodha-only data, rate limiting, automation times, endpoints, DB tables — all built to your spec.  ￼  ￼  ￼

⸻
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS settings (
  k TEXT PRIMARY KEY,
  v TEXT
);

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
  stcg_ltcg TEXT CHECK(stcg_ltcg IN ('STCG','LTCG','NA')) DEFAULT 'NA',
  order_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts);

CREATE TABLE IF NOT EXISTS positions (
  symbol TEXT PRIMARY KEY,
  qty INTEGER NOT NULL,
  avg_price REAL NOT NULL,
  last_price REAL NOT NULL,
  open_ts INTEGER NOT NULL,
  rail TEXT DEFAULT 'CNC',
  sector TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS fifo_lots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  qty INTEGER NOT NULL,
  remaining_qty INTEGER NOT NULL,
  buy_price REAL NOT NULL,
  buy_ts INTEGER NOT NULL,
  rail TEXT DEFAULT 'CNC',
  trade_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_fifo_symbol ON fifo_lots(symbol, remaining_qty);

CREATE TABLE IF NOT EXISTS shadow_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  strategy_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  action TEXT NOT NULL,
  confidence REAL,
  price REAL,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS calendar_events (
  event_date TEXT NOT NULL,
  event_type TEXT NOT NULL,
  title TEXT,
  risk_level TEXT DEFAULT 'medium',
  PRIMARY KEY (event_date, event_type)
);

CREATE TABLE IF NOT EXISTS asm_gsm_symbols (
  symbol TEXT PRIMARY KEY,
  stage TEXT NOT NULL,
  updated_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_pct (
  symbol TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  delivery_pct REAL NOT NULL,
  PRIMARY KEY (symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS fundamentals_cache (
  symbol TEXT PRIMARY KEY,
  roe REAL,
  pe REAL,
  market_cap_cr REAL,
  updated_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS option_iv (
  symbol TEXT NOT NULL,
  strike REAL NOT NULL,
  option_type TEXT NOT NULL,
  iv REAL NOT NULL,
  ltp REAL,
  ts INTEGER NOT NULL,
  PRIMARY KEY (symbol, strike, option_type)
);

CREATE TABLE IF NOT EXISTS strategy_pnl (
  strategy_id TEXT PRIMARY KEY,
  realized_pnl REAL DEFAULT 0,
  trade_count INTEGER DEFAULT 0,
  updated_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS symbol_sectors (
  symbol TEXT PRIMARY KEY,
  sector TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_tax_summary (
  summary_date TEXT PRIMARY KEY,
  ts INTEGER NOT NULL,
  gross_buy REAL NOT NULL,
  gross_sell REAL NOT NULL,
  total_fees REAL NOT NULL,
  net_before_tax REAL NOT NULL,
  est_stcg_tax REAL NOT NULL,
  est_ltcg_tax REAL NOT NULL,
  net_after_tax REAL NOT NULL,
  total_equity REAL NOT NULL,
  trade_count INTEGER NOT NULL
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

CREATE TABLE IF NOT EXISTS instruments (
  tradingsymbol TEXT PRIMARY KEY,
  instrument_token INTEGER NOT NULL,
  exchange TEXT,
  updated_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  strategy_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  event_type TEXT NOT NULL,
  signal TEXT,
  confidence REAL,
  price REAL,
  executed INTEGER DEFAULT 0,
  reason TEXT,
  delivery_id TEXT
);

CREATE TABLE IF NOT EXISTS ingest_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  execution_allowed INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ingest_source_ts ON ingest_log(source, ts);

CREATE TABLE IF NOT EXISTS tick_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  ltp REAL NOT NULL,
  volume INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tick_symbol_ts ON tick_log(symbol, ts);

CREATE TABLE IF NOT EXISTS bar_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  interval TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume INTEGER
);

CREATE INDEX IF NOT EXISTS idx_bar_symbol_ts ON bar_log(symbol, ts, interval);

CREATE TABLE IF NOT EXISTS portfolio_allocation (
  run_ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  weight REAL NOT NULL,
  target_qty INTEGER NOT NULL,
  target_rupees REAL NOT NULL,
  last_price REAL NOT NULL,
  PRIMARY KEY (run_ts, symbol)
);

CREATE INDEX IF NOT EXISTS idx_alloc_run ON portfolio_allocation(run_ts);

CREATE TABLE IF NOT EXISTS option_positions (
  symbol TEXT PRIMARY KEY,
  underlying TEXT NOT NULL,
  strike REAL NOT NULL,
  option_type TEXT NOT NULL,
  expiry TEXT NOT NULL,
  qty INTEGER NOT NULL,
  avg_premium REAL NOT NULL,
  last_premium REAL NOT NULL,
  open_ts INTEGER NOT NULL,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS kite_holdings (
  symbol TEXT PRIMARY KEY,
  qty INTEGER NOT NULL,
  avg_price REAL NOT NULL,
  ltp REAL NOT NULL,
  pnl REAL DEFAULT 0,
  product TEXT DEFAULT 'CNC',
  exchange TEXT DEFAULT 'NSE',
  synced_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_discovery (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id TEXT NOT NULL,
  symbol TEXT,
  conditions TEXT NOT NULL,
  win_rate REAL,
  avg_return REAL,
  sample_count INTEGER,
  discovered_ts INTEGER NOT NULL,
  promoted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pending_orders (
  order_id TEXT PRIMARY KEY,
  ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty INTEGER NOT NULL,
  price REAL NOT NULL,
  rail TEXT,
  strategy_id TEXT,
  reason TEXT,
  status TEXT DEFAULT 'PENDING'
);

CREATE TABLE IF NOT EXISTS depth_snapshots (
  symbol TEXT NOT NULL,
  ts INTEGER NOT NULL,
  bid REAL,
  ask REAL,
  spread_bps REAL,
  bid_qty INTEGER,
  ask_qty INTEGER,
  obi REAL,
  PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS futures_oi (
  symbol TEXT NOT NULL,
  ts INTEGER NOT NULL,
  oi REAL,
  oi_change_pct REAL,
  PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS reconcile_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  mismatches INTEGER,
  details TEXT,
  repaired INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS margin_snapshots (
  ts INTEGER PRIMARY KEY,
  available REAL,
  utilised REAL,
  util_pct REAL
);

CREATE TABLE IF NOT EXISTS shareholding_snapshots (
  symbol TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  promoter_pct REAL,
  fii_pct REAL,
  dii_pct REAL,
  mf_pct REAL,
  public_pct REAL,
  payload_json TEXT,
  ts INTEGER NOT NULL,
  PRIMARY KEY (symbol, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_shareholding_symbol_ts ON shareholding_snapshots(symbol, ts);

CREATE TABLE IF NOT EXISTS corporate_event_outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  event_type TEXT NOT NULL,
  category TEXT,
  side TEXT,
  entity_class TEXT,
  entry_price REAL,
  ret_5d REAL,
  ret_20d REAL,
  labeled_ts INTEGER,
  UNIQUE(event_ts, symbol, event_type, category)
);

CREATE INDEX IF NOT EXISTS idx_event_outcomes_symbol ON corporate_event_outcomes(symbol, event_ts);

CREATE TABLE IF NOT EXISTS strategy_signal_outcomes (
  ledger_ts INTEGER PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  signal TEXT NOT NULL,
  confidence REAL,
  executed INTEGER DEFAULT 0,
  entry_price REAL,
  ret_15m REAL,
  ret_1d REAL,
  labeled_ts INTEGER
);

CREATE INDEX IF NOT EXISTS idx_sso_strategy ON strategy_signal_outcomes(strategy_id);

CREATE TABLE IF NOT EXISTS strategy_lifecycle (
  strategy_id TEXT PRIMARY KEY,
  state TEXT NOT NULL DEFAULT 'candidacy',
  entered_ts INTEGER NOT NULL,
  shadow_signals INTEGER DEFAULT 0,
  probation_trades INTEGER DEFAULT 0,
  last_fitness REAL DEFAULT 0,
  demoted_ts INTEGER
);

CREATE TABLE IF NOT EXISTS discovery_outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id TEXT NOT NULL,
  bar_ts INTEGER NOT NULL,
  forward_return REAL NOT NULL,
  discovered_ts INTEGER NOT NULL,
  UNIQUE(rule_id, bar_ts)
);

CREATE INDEX IF NOT EXISTS idx_discovery_outcomes_rule ON discovery_outcomes(rule_id);

CREATE TABLE IF NOT EXISTS capital_gate_evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  eligible INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_capital_gate_ts ON capital_gate_evaluations(ts);

CREATE TABLE IF NOT EXISTS historical_screen (
  strategy_id TEXT PRIMARY KEY,
  screened_ts INTEGER NOT NULL,
  interval TEXT NOT NULL,
  sample_count INTEGER DEFAULT 0,
  win_rate REAL DEFAULT 0,
  sortino REAL DEFAULT 0,
  calmar REAL DEFAULT 0,
  max_drawdown_pct REAL DEFAULT 0,
  binomial_p REAL DEFAULT 1,
  composite REAL DEFAULT 0,
  cleared INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending',
  lookback_days INTEGER DEFAULT 365
);

CREATE INDEX IF NOT EXISTS idx_historical_screen_cleared ON historical_screen(cleared, composite DESC);

CREATE TABLE IF NOT EXISTS symbol_session_cooldown (
  symbol TEXT NOT NULL,
  session_day TEXT NOT NULL,
  until_ts INTEGER NOT NULL,
  last_loss_pnl REAL DEFAULT 0,
  last_strategy_id TEXT DEFAULT '',
  updated_ts INTEGER NOT NULL,
  PRIMARY KEY(symbol, session_day)
);

CREATE TABLE IF NOT EXISTS loss_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  trade_id INTEGER,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  pnl_inr REAL NOT NULL,
  regime_entry TEXT DEFAULT '',
  regime_exit TEXT DEFAULT '',
  stop_designed INTEGER DEFAULT 0,
  stop_slipped INTEGER DEFAULT 0,
  slippage_inr REAL DEFAULT 0,
  slippage_bps REAL DEFAULT 0,
  signal_failure_pct REAL DEFAULT 0,
  cost_drag_pct REAL DEFAULT 0,
  structural_failure INTEGER DEFAULT 0,
  meta_json TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_loss_ledger_strategy ON loss_ledger(strategy_id, ts DESC);

CREATE TABLE IF NOT EXISTS slippage_parity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty INTEGER NOT NULL,
  predicted_price REAL NOT NULL,
  actual_price REAL NOT NULL,
  signed_bps REAL NOT NULL,
  slippage_inr REAL NOT NULL,
  strategy_id TEXT DEFAULT '',
  source TEXT DEFAULT 'paper'
);

CREATE INDEX IF NOT EXISTS idx_slippage_parity_ts ON slippage_parity(ts DESC);

CREATE TABLE IF NOT EXISTS user_suggestions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  thesis TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  reject_reason TEXT DEFAULT '',
  resolved_ts INTEGER
);

CREATE INDEX IF NOT EXISTS idx_user_suggestions_status ON user_suggestions(status, ts DESC);

CREATE TABLE IF NOT EXISTS meta_model_rows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  ledger_ts INTEGER NOT NULL,
  strategy_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  raw_confidence REAL,
  calibrated_confidence REAL,
  regime TEXT,
  india_vix REAL,
  fii_net_cr REAL,
  bandit_weight REAL,
  label INTEGER
);

CREATE INDEX IF NOT EXISTS idx_meta_model_rows_label ON meta_model_rows(label, ts DESC);
CREATE INDEX IF NOT EXISTS idx_meta_model_rows_ledger_ts ON meta_model_rows(ledger_ts);

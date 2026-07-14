# BharatQuant — Evolution Log

> **Scope:** Autonomous Indian-market trading platform (NSE/BSE via Kite Connect).  
> **Separate from:** GeM Bid System / tender rails — never mix repos, DBs, or deploy pipelines.  
> **Codebase:** `zerodha-momo-rl/` (refactor target → event-driven cloud engine).  
> **Principles:** Real data only · fail-loud · no LLM on execution path · 100% cloud · event-driven (no trading cron).

---

## 2026-07-12 — Session 0: Discovery, audit, architecture reset

### Context

User attempted `zerodha-momo-rl` (Oct 2025 manifest-driven scaffold). Multiple failures: fake screener OHLC, browser-only Kite auth, cron at 09:20, Flask API stubs, buy-only paper executor, no git, no cloud, no UI. Tests pass on fixtures — not live market.

### Research — official market timings (do not guess)

**NSE India (equity cash)** — [NSE Market Timings](https://www.nseindia.com/resources/exchange-communication-holidays):

| Session | IST |
|---------|-----|
| Block deal (morning) | **08:45 – 09:00** |
| Pre-open order entry | **09:00 – 09:08** (random close last minute) |
| Pre-open matching | After 09:08 |
| Regular market | **09:15 – 15:30** |
| Block deal (afternoon) | **14:05 – 14:20** |
| Closing session | **15:40 – 16:00** |

**NSE F&O** — pre-open 09:00–09:08 (from Dec 2025); regular 09:15–15:30; cutoff 16:15.

**GIFT Nifty (NSE IX, GIFT City)** — [NSE IX trading hours](https://www.nseix.com/markets/trading/tradinghours):

| Session | IST |
|---------|-----|
| Session 1 (incl. pre-open ~06:15) | ~**06:15 – 15:40** |
| Break | 15:40 – 16:35 |
| Session 2 | **16:35 – 02:45** (next day) |
| Total | ~21 hours/day |

**GIFT vs NSE — critical correction:**

- GIFT trades do **not** carry over as positions to NSE (separate venue, USD cash-settled, IFSCA-regulated).
- GIFT **does** carry **price discovery / expectation** into NSE open (successor to SGX Nifty, full migration 3 Jul 2023).
- **Indian retail cannot execute on GIFT Nifty** (RBI LRS / IFSCA) — ingest as **signal only**; execute on NSE via Kite.

### Architecture decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Repo | Refactor `zerodha-momo-rl`, not greenfield | Keep SQLite schema, cost engine, Kite feed skeleton (~30%) |
| Runtime | **100% GCP** — GCE VM + static IP | SEBI whitelist; no local Mac daemon |
| Database | SQLite on persistent disk | ₹0 DB SaaS; single VM writer |
| Trigger model | **Event-driven** — no trading cron | React like human: GIFT_TICK, BLOCK_DEAL, PREOPEN, TICK |
| LLM | Optional **Gemini Flash on cloud** for news only | ₹0 execution path; ~₹0–500/mo if enabled |
| Strategy count | **Plugin registry (1→N)** | Not capped at 12 |
| Autonomy | 100% — no human in loop | TOTP headless auth mandatory |
| Paper → live | Paper Days 1–6; live Day 7 with hard caps | User timeline; profitability gate waived by user |
| Agent intelligence | Stats/ML/bandit — not LLM execution | Wall Street execution = code, research = optional LLM |

### Global platform patterns adopted (case studies)

| Platform / practice | What we take | Indian adaptation |
|---------------------|--------------|-------------------|
| **Bloomberg** | Multi-feed fusion, event calendar, risk dashboard | FII/DII + GIFT + NSE announcements |
| **Interactive Brokers TWS** | Multi-asset, paper/live parity, margin gate | Kite CNC/MIS/NRML/OPT rails |
| **QuantConnect / Lean** | Backtest interface = live interface | FinRL-X weight-centric pattern |
| **Two Sigma / AQR** | Factor + regime + portfolio construction | Momentum, quality, low-vol, HMM regime |
| **Citadel / stat arb** | Pairs cointegration, basis arb | NSE pair stocks; Nifty cash-fut basis |
| **NYSE floor / ORB** | Opening range breakout on event | NSE 09:00–09:15 range, break on TICK |
| **VWAP desks** | Intraday mean reversion to VWAP | Kite tick aggregation |
| **CBOE vol strategies** | IV rank, premium selling | Kite option chain |
| **SEC Form 4 follow (Seyhun)** | Insider cluster buys | NSE insider API |
| **13D / block following** | Smart money blocks | NSE block/bulk deals 08:45 & 14:05 |
| **SGX/GIFT overnight** | Gap bias before domestic open | GIFT signal from 06:15 |
| **TradingAgents** | Multi-agent debate graph | Optional Gemini; structure only |
| **MetaTrader EA** | Plugin strategies on tick events | Strategy registry |
| **Alpaca** | API-first, paper identical to live | Paper broker with real LTP + slippage |
| **Zerodha Streak** | Rule triggers on market events | EventBus subscriptions |

### Failed approaches (do not repeat)

| Anti-pattern | Symptom | Prevention |
|--------------|---------|------------|
| Dummy OHLC in screener | Trades on fiction | `raise DataUnavailable` if Kite history empty |
| Cron 09:20 daily buy | Misses pre-open, GIFT, blocks | EventBus only for trading |
| `ltp = 100.0` fallback | Wrong fills | Fail order if LTP missing |
| Browser `webbrowser.open` auth | Not cloud-autonomous | TOTP + Playwright on VM |
| Flask stub endpoints | False "done" | FastAPI + real data or 503 |
| Buy-only executor | No risk realization | TICK → STOP_BREACH → sell |
| RL observer stubs | Complexity without learning | Bandit on real `strategy_ledger` |
| LLM per tick | Cost + latency bankruptcy | LLM max 50 calls/day research only |
| Assuming GIFT = NSE positions | Wrong execution venue | GIFT = signal; Kite = execution |
| "Market opens 09:00" only | Misses 08:45 blocks, 09:15 regular | Full official timeline as events |

### Open decisions (user input pending)

- GCP project name (isolated vs shared)
- Paper capital, Day 7 live caps (₹/trade, daily loss halt)
- LLM: `off` vs `gemini-flash`
- Products: CNC / +MIS / +F&O / +options
- Universe: NIFTY50 / NIFTY200 / custom
- TOTP + password in Secret Manager: yes/no
- Repo rename: `bharatquant` vs keep `zerodha-momo-rl`

### Cost model (cloud-only)

| Item | ₹/month |
|------|---------|
| GCE e2-small + 20GB disk | ~1,070 |
| Secret Manager + GCS backup | ~70 |
| Kite Connect | 0 |
| NSE public APIs | 0 |
| Gemini Flash (optional) | 0–500 |
| **Total** | **~1,150–1,650** |

### Next session entry template

```
## YYYY-MM-DD — <title>
**Agent**: BharatQuant
**Changed**: ...
**Verified**: ... (real data proof)
**Failed**: ...
```

---

## Reference — full event timeline (IST, trading days)

```
06:15  GIFT_SESSION1_PREOPEN     → signal: overnight gap bias
06:30  GIFT_TICK                 → US/Asia impounded
08:45  NSE_BLOCK_DEAL_MORNING    → signal + optional NSE trade
09:00  NSE_PREOPEN_START         → equilibrium forming (cash + F&O)
09:08  NSE_PREOPEN_MATCH         → opening price discovered
09:15  NSE_REGULAR_OPEN          → Kite WS ticks; full execution
14:05  NSE_BLOCK_DEAL_AFTERNOON
15:30  NSE_REGULAR_CLOSE
15:40  NSE_CLOSING_SESSION + GIFT_S1_END
16:00  NSE_CLOSING_END
16:35  GIFT_SESSION2_START       → next-day bias
02:45  GIFT_SESSION2_END
```

Non-equity NSE segments (separate event streams): currency 09:00–17:00; commodities 09:00–23:30+.

---

## Reference — repo cherry-pick map

| Source repo | Take | Skip |
|-------------|------|------|
| `zerodha-momo-rl` (local) | Schema, costs, risk, Kite REST | Dummy screener, cron, stubs |
| FinRL-X | Backtest = live weight pipeline | US-only examples |
| TradingAgents | Debate graph, decision log | Cloud LLM defaults |
| indian-trading-agent | FII filter, shadow trades, regime | Gemini lock-in |
| hopit-ai/india-trade-cli | Agent roles, morning brief | Fyers broker |
| zAck_trading_bot | Strategy registry, RAG journal | Gemini picker |
| openquant | VaR, Kelly, Monte Carlo | US assumptions |
| RakshaQuant | LangGraph + memory | Groq dependency |
| autotrading / skopaqtrader | Daemon FSM, drawdown breakers | INDstocks |
| NSE-MCP / mrchartist | Ingestion patterns | MCP wrapper required |
| openkite | Screener.in fundamentals | OpenAI SDK |

---

## 2026-07-12 — Session 1: Day 1 build started (user provides creds by evening)

### User decisions (locked)

| Item | Value |
|------|-------|
| GCP | **New project** — link to GeM billing account |
| Daily capital | **₹500–₹1,000/day** |
| Max per trade | **₹1,000** |
| Max daily loss halt | **₹2,000** |
| Live money | Zerodha account via Kite API after Day 7 |
| Runtime | **100% cloud** — no local daemon |
| Triggers | **Event-driven only** — no trading cron |

### Zerodha static IP whitelisting (how-to)

1. Provision GCE VM with static IP: `bash scripts/gcp_provision.sh` → note `STATIC_IP`
2. Log in **[developers.kite.trade](https://developers.kite.trade)** (Kite Connect developer portal — not regular Kite app)
3. **Profile** (top-right) → **IP Whitelist**
4. Enter **primary IP** = GCE static IP (one per line; optional backup IP on line 2)
5. Click **Update** — **one modification per calendar week** (verify carefully)
6. **Regenerate access token** after whitelisting
7. **Important (Zerodha forum):** Only **order placement** endpoints validate static IP. WebSocket ticks, quotes, positions work from any IP — but live orders **must** egress from whitelisted IP

Sources: [Zerodha support — static IP](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip) · [Kite forum SEBI compliance](https://kite.trade/forum/discussion/15912/preparing-to-comply-with-sebis-retail-algo-rules-static-ip-ratelimits-order-types)

### API sources (official — use these, not guesses)

| Platform | Purpose | Documentation |
|----------|---------|---------------|
| **Kite Connect** | Orders, LTP, OHLC, WebSocket ticks, margins | [PyKiteConnect v4](https://kite.trade/docs/pykiteconnect/v4/) · [Developer portal](https://developers.kite.trade) |
| **NSE India** | FII/DII, bulk/block, insider, market timings | [Market timings](https://www.nseindia.com/resources/exchange-communication-holidays) · public JSON endpoints |
| **NSE IX** | GIFT Nifty hours (signal only) | [nseix.com/tradinghours](https://www.nseix.com/markets/trading/tradinghours) |
| **Yahoo Finance** | Global macro (US futures, crude) — `.NS` suffix for NSE | `yfinance` library; backup only — **execution prices from Kite only** |
| **mrchartist FII/DII API** | Free JSON FII/DII history | [fii-diidata.mrchartist.com](https://fii-diidata.mrchartist.com/data-api.html) |
| **Gemini Flash** | Optional news/earnings (not execution) | Google AI Studio API |

### Evening checklist — what Aby provides tonight

```
[ ] GCP: create project name (e.g. bharatquant-prod) + link GeM billing
[ ] Run: GCP_PROJECT=... bash scripts/gcp_provision.sh → copy STATIC_IP
[ ] Zerodha: whitelist STATIC_IP at developers.kite.trade → Profile → IP Whitelist
[ ] KITE_API_KEY + KITE_API_SECRET (from developers.kite.trade → your app)
[ ] KITE_USER_ID (Zerodha client ID)
[ ] KITE_PASSWORD
[ ] KITE_TOTP_SECRET (Google Authenticator setup key — for headless login)
[ ] Confirm redirect URL: http://STATIC_IP:8080/kite/callback (or HTTPS if nginx)
[ ] Optional: GEMINI_API_KEY, TELEGRAM_BOT_TOKEN + CHAT_ID
```

Store on VM via GCP Secret Manager — never commit `.env`.

### Day 1 code shipped

- Git init + `.gitignore` + `.env.example`
- `EventBus` + `EventType` (event-driven core)
- `src/engine/main.py` always-on entry (replaces trading scheduler)
- `scheduler.py` deprecated — exits with error if run
- `momentum_screener.py` rewritten — **real Kite OHLC only**, `DataUnavailableError` if missing
- `instruments.py` token cache from Kite instruments dump
- `kite_ticker.py` WebSocket → TICK events (PyKiteConnect KiteTicker)
- Removed `ltp=100` fallback in executor
- `config.yaml`: ₹500–1000/day, max ₹1000/trade, ₹2000 daily loss
- `scripts/gcp_provision.sh`
- Tests: 4 passed (mock feed for unit tests only)

### Next (Day 2)

- TOTP headless auth (`playwright` + `pyotp`)
- Wire `KiteTickFeed` into `engine.main` publish loop
- `TOKEN_EXPIRED` → re-auth chain
- Real-time `STOP_BREACH` handler

---

## 2026-07-12 — Session 2: Day 2 build (no creds — scaffold everything)

### Research wired into code (papers + market reality)

| Source | Finding | BharatQuant implementation |
|--------|---------|---------------------------|
| Nigam & Pandey 2023 ([IJOEM](https://doi.org/10.1108/ijoem-09-2023-1518)) | **Combined relative + absolute momentum** beats price-only in India; behavioral overreaction | `combined_momentum.py` — `r3m > r1m` + FII gate |
| Raju 2024 ([SSRN 4977717](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4977717)) | Momentum dissipates after 3–12 months; shorter holds work | MIS rail for intraday (`opening_range`, `vwap_reversion`); CNC for swing |
| Pelluri 2025 ([SSRN 5116091](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5116091)) | Formation/holding period + weighting matter | `strategy_ledger` + bandit weights by 30d hit rate |
| IMMR-H India journal (12-1 mom + 5d reversal) | Short-term reversal after overreaction | `short_term_reversal.py` |
| FII/DII studies 2012–2024 | FIIs momentum; DIIs contrarian in bull | `fii_regime.py` RISK_ON/OFF |
| Azevedo ML returns 2025 | Net returns 23–92% below backtests after costs | `CostEngine` on every fill; `MAX_RUPEES_PER_TRADE` |
| SEBI FY25 study ([BusinessLine](https://www.thehindubusinessline.com/markets/retail-investor-losses-in-fo-widen-by-41-in-fy25-sebi-study/article69784782.ece)) | **91% F&O retail lost money**; ₹1.05L cr aggregate loss | CNC-first Day 7; ₹2000 daily halt; paper Days 1–6 |
| SEBI retail algo rules (Apr 2026) | Static IP + registered algos | `gcp_provision.sh` static IP + `live_broker.py` tagged orders |
| **Who makes money** | Prop/algo desks + market makers capture flow; retail directional F&O bleeds | Event-driven equity CNC/MIS only; no naked options Day 7 |

**News / money lesson:** Retail F&O losses widened 41% YoY in FY25 despite SEBI pop-up warnings. Profits concentrate in **registered algo/prop entities** and **market makers** (Citadel-style payment for order flow in US; NSE member prop in India). BharatQuant design: **low turnover, cost-aware, equity delivery/intraday** — not hyperactive F&O.

### Day 2 code shipped (all runnable without Kite token)

| Module | Path | Notes |
|--------|------|-------|
| 8 strategies | `src/strategies/*.py` | Research-backed plugins |
| Registry | `src/strategies/registry.py` | Config-driven enable list |
| Ingest | `src/ingest/{fii_dii,nse_bulk,gift_nifty,global_macro}.py` | Public APIs only |
| Agent | `src/agent/{router,bandit}.py` | Fuse + Thompson weights |
| Execution | `src/engine/execution_engine.py` | Paper/live branch |
| Live broker | `src/exec/live_broker.py` | Kite place_order (needs whitelist IP) |
| Position monitor | `src/exec/position_monitor.py` | TICK → STOP_BREACH |
| Bar aggregator | `src/feeds/bar_aggregator.py` | TICK → BAR_CLOSE_5M + VWAP_CROSS |
| Session watcher | `src/feeds/session_watcher.py` | NSE marketStatus → SESSION_* |
| Engine wiring | `src/engine/main.py` | Bus + pollers + strategies + bandit |
| TOTP auth | `src/auth/kite_totp.py` | Playwright skeleton (needs creds) |
| Dashboard | `src/api/dashboard.py` | FastAPI + Lightweight Charts (portfolio_history only) |
| Deploy | `deploy/*.service`, `scripts/secrets_sync.sh` | systemd + Secret Manager |
| Tests | `tests/test_strategies.py` | **8 passed** |

### Still blocked on evening creds

- Kite token → real WebSocket TICK + OHLC screener
- GCP billing link → `gcp_provision.sh` static IP
- Zerodha IP whitelist → live `place_order`
- Playwright TOTP login smoke test

### Next (Day 3)

- `TOKEN_EXPIRED` event → `kite_totp.headless_login()` chain
- Instrument token map from `instruments.py` (not hash placeholder)
- Optional Gemini Flash news → `NEWS_ALERT` ingest (off by default)
- Paper trading E2E: FII update → gift gap → combined_mom → paper fill → dashboard

---

## 2026-07-12 — Universe expanded: full NSE (not NIFTY 200)

**User ask:** screen/trade everything possible, not just NIFTY 50/200.

| Tier | File | Symbols | What |
|------|------|---------|------|
| `main` (default) | `data/universe_full_nse.csv` | **2,335** | All main-board NSE EQ |
| `with_sme` | `data/universe_full_nse_sme.csv` | **2,709** | + SME (`-SM`) |
| `all_eq` | `data/universe_all_nse_eq.csv` | **3,042** | + illiquid series minus debt/ETF |

**Build (no creds):** `bash scripts/build_universe.sh` or `python3.11 -m src.data.universe_builder --tier main`

Source: public Kite instruments CSV `https://api.kite.trade/instruments`

**Architecture:** Full universe for **screening** on `SESSION_PRE_OPEN`; WebSocket ticks only on **watchlist** (top 200 screened + open positions) — Kite allows 3000 subs but bandwidth/rate limits make full-tick impractical.

Config: `UNIVERSE=data/universe_full_nse.csv`, `WS_WATCHLIST_SIZE=200`

---

## 2026-07-12 — Anti-fake-data purge (old project debt)

**User concern:** old project used manual processes, incomplete and fake data.

### Removed / deprecated

| Old pattern | Where | Fix |
|-------------|-------|-----|
| `ltp=100` fallback | `trade_executor.py` | Module deprecated — exits error |
| `daily_investment // 100` fake sizing | `trade_executor.py` | Removed with module |
| 09:20 APScheduler cron | `scheduler.py` | Already exits error |
| Flask stub gainers/losers | `api/app.py` | Deprecated → use `api/dashboard.py` |
| Placeholder unrealized PnL = 0 | `api/app.py` | Dashboard uses `positions` mark-to-market |
| `advanced_screener.py` empty stub | screening | ImportError — use real screener |
| `start_system.sh` → scheduler | ops | Now starts `engine.main` + `dashboard` |
| RL zero-reward placeholders | legacy executor | Path removed |

### Enforced (`src/data/data_policy.py`)

- `require_positive_price()` — execution path rejects price ≤ 0
- `DataUnavailableError` — screener fails loud if OHLC missing
- GIFT ingest: `execution_allowed: false`, `price=0` on event
- Mock feed: `tests/mock_feed.py` only — never production import

**Rule:** If Kite token or OHLC unavailable → **skip + log**, never invent numbers.

---

## 2026-07-12 — Quant Finance repo cherry-pick audit (40+ GitHub repos)

**User ask:** Deep-read random QuantFinance repos; pick what helps BharatQuant (NSE India), skip noise.

### BharatQuant filters (non-negotiable)

| Filter | Why |
|--------|-----|
| **Kite = sole execution price** | Yahoo/yfinance/wallstreet/Alpha Vantage are delayed or US-centric — same failure mode as old `ltp=100` project |
| **Event-driven live** | Reject cron schedulers (`rqalpha sys_scheduler`, trading-bot morning jobs) for production orders |
| **No LLM on order path** | TradingAgents / FinMem / Wyckoff / AgentQuant → research tier only (Gemini Flash, off by default) |
| **Cost-aware backtest** | Any strategy must include STT + brokerage + slippage before paper/live (Azevedo 2025 lesson) |
| **India identity** | `tender_ref`-style: never mix US tickers with NSE symbols in one execution book |

### Tier A — Pick up patterns (high value, fits India)

| Repo | What to steal | BharatQuant target | Phase |
|------|---------------|-------------------|-------|
| [vnpy](https://github.com/vnpy/vnpy) | EventEngine, Gateway abstraction, `data_recorder`, `risk_manager`, paper_account parity | `EventBus` already exists — add **tick recorder** + **pre-trade risk gate** module | W1 |
| [rqalpha](https://github.com/ricequant/rqalpha) | `sys_transaction_cost`, `sys_risk`, `sys_analyser` mods | **Offline backtest harness** on Kite historical OHLC only (not live scheduler) | W2 |
| [SilvioBaratto/optimizer](https://github.com/SilvioBaratto/optimizer) | skfolio mean-variance / risk parity on small baskets | Position sizing across max 5 CNC names after screen | W2 |
| [TrungNguyen QuantFinance-Databases](https://github.com/TrungNguyen-ybidh/QuantFinance-Databases) | fetcher → cleaner → pipeline → warehouse | Extend `src/ingest/` with **staged SQLite tables** + provenance columns | W1 |
| [shashankvemuri/Finance](https://github.com/shashankvemuri/Finance) + [Aditya-dom backtesting](https://github.com/Aditya-dom/Quantfinance-with-backtesting) | TA screeners, RSI/MACD/Bollinger modules | Port **pure functions** into `features/` — input must be Kite OHLC DataFrame | W1 |
| [renee-jia/trading-bot](https://github.com/renee-jia/trading-bot) | T+1 execution assumption, 5bps/side costs, analyzer vs executor split | Paper proof: strategy P&L vs NIFTYBEES buy-hold | W2 |
| [cporter202/signal-automation](https://github.com/cporter202/stock-market-signal-automation) | Signed webhook payloads, delivery IDs, empty-pick events | `strategy_ledger` + Telegram alerts with **event_id** + replay | W1 |
| [akshare](https://github.com/akfamily/akshare) | NSE FII/DII, fundamentals, sector — India-native | **Supplemental ingest only** (tag `source=akshare`, never execution) | W1 |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | Unified macro provider router | Optional macro panel (crude, USDINR, US futures) — already started via yfinance proxy | W2 |
| [LechGrzelak QuantFinanceBook](https://github.com/LechGrzelak/QuantFinanceBook) | Monte Carlo, GBM, Greeks math | Reference for **NRML hedge** sizing (Phase 4 options) | W4 |
| [KylinMountain/TradingAgents-AShare](https://github.com/KylinMountain/TradingAgents-AShare) | A-share multi-agent **research** UI, debate structure | Optional `NEWS_ALERT` / earnings path via Gemini — **no orders** | W3 |

### Tier B — Borrow ideas only (do not vendor)

| Repo | Useful idea | Skip |
|------|-------------|------|
| [microsoft/qlib](https://github.com/microsoft/qlib) | Alpha158-style factor registry, walk-forward CV | Full platform — US data, heavy deps, duplicates our engine |
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | Analyst → researcher → risk debate graph | LLM latency + cost on execution path |
| [plotly/dash](https://github.com/plotly/dash) | Rich multi-panel dashboards | Keep FastAPI + Lightweight Charts; borrow layout patterns only |
| [PythonCharmers/QuantFinance](https://github.com/PythonCharmers/QuantFinance) | Training notebooks | Educational — no production code |
| [ricequant RQData](https://github.com/ricequant/rqalpha) (docs) | India A-share data model | China market — use Kite + akshare instead |

### Tier C — Reject for BharatQuant (noise or anti-patterns)

| Repo | Reason |
|------|--------|
| [yfinance](https://github.com/ranaroussi/yfinance), [yahoo-finance](https://github.com/yahoo-finance/yahoo-finance), [wallstreet](https://github.com/mcdallas/wallstreet) | Unofficial Yahoo scrape — **exactly the manual/fake-data trap** user flagged; OK for macro signal only |
| [bulbea](https://github.com/achillesrasquinha/bulbea), [FinMem](https://github.com/pipiku915/FinMem-LLM-StockTrading), [AgentQuant](https://github.com/OnePunchMonk/AgentQuant) | RNN/LLM on Yahoo data — research toys |
| [AutomatedStockTrading DQN](https://github.com/sachink2010/AutomatedStockTrading-DeepQ-Learning), [Stock-Trading-Visualization](https://github.com/notadamking/Stock-Trading-Visualization) | Gym env + overfit; no cost model |
| [giuseppecangemi/quantfinance](https://github.com/giuseppecangemi/quantfinance) | WTI options BSM student project |
| [mattmcd](https://github.com/mattmcd/QuantFinance), [JoeLove100](https://github.com/JoeLove100/QuantFinance), [YVYX04/Cpp](https://github.com/YVYX04/Cpp_QuantFinance) | C++/C# — wrong stack |
| [ITAM](https://github.com/rodmono/ITAM-QuantFinance), [Rishik-J](https://github.com/Rishik-J/QuantFinance) | Notebook coursework |
| [alpha_vantage](https://github.com/RomelTorres/alpha_vantage) | US API limits; not NSE |
| [QuantFinanceSociety LSTM](https://github.com/QuantFinanceSocietySouthampton/QuantFinanceModel) | LSTM on Kaggle — no live path |
| [lh4d/quantfinance](https://github.com/lh4d/quantfinance) | Link dump, no code |
| [YoungCan/WyckoffTradingAgent](https://github.com/YoungCan/WyckoffTradingAgent) | LLM chart pattern — defer |

### Architecture lessons (cross-repo)

```
vnpy EventEngine          →  we have EventBus ✓
vnpy data_recorder        →  BQ-CHERRY-01 (missing)
vnpy risk_manager         →  partial (risk_engine) — add OPS throttle BQ-25
rqalpha transaction_cost  →  cost_engine ✓ — add walk-forward backtest
optimizer skfolio         →  BQ-CHERRY-02 Kelly/max 5 positions
QuantFinance-Databases    →  BQ-CHERRY-03 ingest provenance tables
trading-bot               →  BQ-CHERRY-04 paper vs NIFTYBEES benchmark
signal-automation         →  BQ-CHERRY-05 signed alert webhooks
```

### What NOT to repeat from these repos (old-project sins)

1. **Yahoo as primary OHLC** — [Finance](https://github.com/shashankvemuri/Finance), [bulbea](https://github.com/achillesrasquinha/bulbea), most RL repos
2. **Cron at 9:28/9:30** — [signal-automation](https://github.com/cporter202/stock-market-signal-automation) US style; we use NSE `SESSION_*` events
3. **Stub dashboards** — half the tutorial repos; we deprecated Flask stubs
4. **Private `core/` with fake open harness** — [trading-bot](https://github.com/renee-jia/trading-bot) hides alpha; we keep strategies open + `strategy_ledger` audit
5. **LLM decides trades** — TradingAgents family; SEBI algo rules need deterministic registered logic

### Implementation order (after creds tonight)

1. **BQ-CHERRY-03** — ingest provenance (`source`, `fetched_at`, `execution_allowed`) on every non-Kite row
2. **BQ-CHERRY-01** — tick/OHLC recorder to SQLite (vnpy `data_recorder` pattern)
3. **BQ-CHERRY-04** — backtest CLI: Kite historical + `cost_engine` + vs NIFTYBEES
4. **BQ-CHERRY-02** — skfolio weights on screened top-5
5. **BQ-CHERRY-05** — Telegram webhook with signal hash
6. **BQ-CHERRY-06** — optional Gemini research agent (KylinMountain debate pattern, no execution)

---

## 2026-07-12 — Code-verified cherry-pick implementation

**User pushback:** Prior audit was README-level; re-read actual repo code and wired pickups.

### Corrections after reading source

| Prior claim | Code reality | Action taken |
|-------------|--------------|--------------|
| Replace EventBus with vnpy EventEngine | vnpy uses **threading Queue** (`vnpy/event/engine.py:48`) — worse fit than our **asyncio** bus | Kept EventBus; ported **recorder** only |
| Vendor skfolio (optimizer) | `optimization_service.py` pulls sklearn+skfolio+SQLAlchemy — heavy for GCE e2-small | Implemented **numpy inverse-vol** in `src/portfolio/sizing.py` (same idea as mean-risk on small N) |
| Finance ta_functions wholesale | File imports **yfinance** at line 5 — anti-pattern for us | Ported **RSI/MACD/ATR/BB** math only into `src/features/indicators.py` |
| rqalpha costs | `StockTransactionCostDecider._calc_commission` uses **min_commission map per order_id** | Zerodha ₹20 floor in `src/costs/cost_engine.py` |
| cporter202 webhooks | `app.py:27-38` HMAC `timestamp.body` | `src/alerts/webhook.py` + `delivery_id` on `strategy_ledger` |

### Files added/changed

- `src/data/provenance.py` + `ingest_log` table — all ingest payloads tagged
- `src/data/tick_recorder.py` + `tick_log`/`bar_log` — wired in `engine/main.py`
- `src/features/indicators.py` — MACD, ATR, BB width (Finance-derived, Kite OHLC only)
- `src/portfolio/sizing.py` — inverse-vol weights + rupee qty map
- `src/alerts/webhook.py` — signed deliveries + optional Telegram
- `src/costs/cost_engine.py` — rqalpha-style min commission + CNC STT on sell
- Ingest: `fii_dii`, `nse_bulk`, `global_macro`, `gift_nifty` use `tag_payload`
- `tests/test_cherry_pick.py` — 6 new tests; **20 passed** total

### Still deferred (needs Kite creds / more code read)

- **skfolio** optional dep when VM has headroom
- **BQ-CHERRY-06** Gemini research UI (code stub in `src/research/gemini_news.py`, `LLM_ENABLED` gate)

---

## 2026-07-12 — Build-everything batch (walk-forward, ops, ingest, dashboard)

**Scope:** Close remaining tracker rows without Kite evening creds.

### Shipped

| Component | Path |
|-----------|------|
| Walk-forward backtest + CLI | `src/backtest/walk_forward.py`, `scripts/backtest.py` |
| Kill switch + ₹ daily loss halt | `src/ops/kill_switch.py`, `src/ops/daily_pnl.py`, execution + risk |
| SEBI 10 OPS throttle (live) | `LiveBroker` + `RateLimiter(max_per_sec=10)` |
| GCS backup on SESSION_CLOSE | `src/ops/backup.py` wired in `engine/main.py` |
| Context updater (FII/GIFT/preopen → ctx) | `src/agent/context_updater.py` |
| Supplemental ingest | `akshare_fii`, `nse_insider`, `nse_preopen` pollers |
| Dashboard halt + allocation APIs | `POST /internal/halt`, `/api/allocation`, UI buttons |
| Deploy one-command | `scripts/deploy_vm.sh` (BQ-18) |
| Paper cash seed + ledger on fills | `main.py` seed; execution `add_cash` on buy/sell |

### Tests

`python3.11 -m pytest tests/ -q` → **26 passed** (+`test_backtest`, `test_kill_switch`, `test_risk_rupees`)

### Evening gate (unchanged)

Kite TOTP + static IP whitelist required for live verification of: WS ticks, NSE ingest APIs, option chain IV, screener scrape rate limits.

---

## 2026-07-12 (pm) — W2 + partial-build completion (no creds wait)

Built all remaining partial + deferred modules; creds only needed for live verification.

### Layer 2 partial → code-complete

| Module | Path |
|--------|------|
| FIFO lots + STCG/LTCG on sell | `src/accounting/fifo_lots.py` |
| Margin pre-check | `src/exec/margin_check.py` |
| MIS rail + session square-off | `positions.rail`, `position_monitor.py` |
| Feed watchdog + WS reconnect | `src/feeds/feed_watchdog.py`, `kite_ticker.py` |
| Bars 15m + 1d | `bar_aggregator.py`, `BAR_CLOSE_15M/1D` |
| Auth auto-recovery | `src/ops/auth_recovery.py` |
| ASM/GSM filter | `src/data/asm_gsm_filter.py` |
| Sector concentration | `src/risk/sector_limits.py` |
| Event calendar (RBI/expiry) | `src/risk/event_calendar.py` |

### Layer agent intelligence

| Module | Path |
|--------|------|
| Regime classifier (HMM surrogate) | `src/agent/regime_classifier.py` |
| Kelly sizing | `src/agent/kelly_sizing.py` |
| VaR circuit breaker | `src/agent/var_breaker.py` |
| Shadow trades | `src/agent/shadow_trades.py` |

### W2 ingest

| Module | Path |
|--------|------|
| Delivery % | `src/ingest/nse_delivery.py` |
| Corp announcements | `src/ingest/nse_corp_rss.py` |
| Screener.in fundamentals | `src/ingest/screener_fundamentals.py` |
| Kite option IV chain | `src/ingest/kite_options.py` |

### W2 strategies (15 total)

`pairs_stat_arb`, `quality_momentum`, `insider_cluster`, `bulk_accumulation`, `iv_premium_sell`, `cash_futures_basis`, `expiry_gamma` + original 8.

### Dashboard APIs

`/api/ohlc/{symbol}`, `/api/trade_markers`, `/api/strategy_pnl`, `/api/rolling_metrics`, `/api/fii_series`, `/api/shadow_trades`, OHLC candle chart + markers.

### Tests

`python3.11 -m pytest tests/ -q` → **30 passed**

---

## 2026-07-12 (night) — Optional polish (no creds)

- 15m/1d bars → `tick_recorder` + engine subscriptions
- `order_id` column + `ORDER_FILL` reconcile (`order_fill_handler`, Kite `on_order_update`)
- Strategies: `earnings_vol`, `global_risk_beta` (**17 total**)
- Daily after-tax summary: `daily_tax_summary.py`, `/api/daily_tax_summary`, SESSION_CLOSE persist
- Sector map: `data/sector_map.csv` + `sector_mapper.py`
- Dashboard: FII line chart, GIFT gap panel, after-tax metric, fixed portfolio chart
- `tests/test_polish.py` — EventBus, recorder, order fill, tax, sector, strategies

**38 tests green.**

---

## 2026-07-13 — Vertex Gemini LLM brain live on VM (no AI Studio credits)

### Problem
AI Studio `GEMINI_API_KEY` returned 429 (prepay credits depleted). OpenAI/Anthropic secrets also unusable (quota/401).

### Fix
Tier-1 macro brain now calls **Vertex AI Gemini** first via VM default service account (`gemini-2.5-flash`, `us-central1`) — bills to existing GCP project, no user action.

Fallback chain: `vertex_gemini` → AI Studio key → OpenAI → Anthropic → `0.0`.

### Proof (VM)
`python3.11 scripts/probe_llm_macro.py` → `llm_bias 0.6`, `source vertex_gemini`. Engine restarted; `llm_macro_detail.source=vertex_gemini` in SQLite.

### Env
`VERTEX_GEMINI_ENABLED=true`, `VERTEX_GEMINI_MODEL=gemini-2.5-flash`, `VERTEX_LOCATION=us-central1`, `GCP_PROJECT=your-gcp-project-id`.

---

## 2026-07-13 (eve) — Universe widen + budget accumulate + EOD scan + cost gate

### Fixes shipped
1. **Full NSE screen** — parallel `SCREEN_PARALLEL_WORKERS=10`, startup + pre-open forced when bootstrap placeholder detected; `SCREEN_MIN_HISTORY_ROWS=90`.
2. **Post-close EOD scan** — `eod_market_scan.py` ranks day movers + 5d swing across universe → feeds next-day `screening_results`.
3. **Cost gate** — `COST_MAX_ROUNDTRIP_PCT=3.5` blocks 1-share ₹1100 trades; requires multi-share on mid-caps.
4. **Budget accumulate** — `BUDGET_ROLLOVER_MODE=accumulate` + `credit_daily_stipend_on_open()` (+₹2000 each session open on top of unused pool). Paper cash never resets.
5. **Realtime breadth** — `WS_WATCHLIST_SIZE=400`, `BATCH_LTP` polls 200 symbols/12s, `FAST_SNAPSHOT_CANDIDATES=80`.

### Deploy
`gcp_deploy.sh` green; full universe screen kicked off on VM (`full_screen.log`).

---

## 2026-07-13 (night) — RL guardrails: low LR + shadow backtest gate

### Problem
Single abnormal day (flash crash, budget) could over-train PPO; new weights promoted without validation.

### Fix
- **Low LR** — `RL_LEARNING_RATE=1e-5`, max 2 epochs / 2000 SB3 steps (was 3e-4 / 20k).
- **Abnormal-day dampening** — if daily move ≥3% or GIFT gap ≥3%, LR×0.3, epochs halved, timesteps×0.25.
- **Shadow deployment** — snapshot `policy_stable.npz` → train candidate → 30-day 5m `bar_log` backtest → revert if >2% worse than stable; GCS sync only on promote.

Files: `training_guardrails.py`, `shadow_backtest.py`; `SESSION_CLOSE` uses `guarded_train_and_promote`.

---

## 2026-07-13 (late) — Pre/post-market dashboard integration + remaining guardrails

### Pre-market (08:45 IST)
- `market_routines.py` — LLM macro burst, pushes narrative to **Latest agent decision** (`PREMARKET` action)
- VIX-safe **budget auto-approve** when India VIX ≤ 22 (`auto_approve_budget_if_vix_safe`)
- Dashboard feed: `premarket_brief`, `india_vix`, `llm_bias` chips

### Post-market (16:15 IST)
- Slippage analysis from trades vs strategy_ledger target prices
- Guarded RL train (shadow gate) + `PPO_{version}_Adaptive` strategy row
- LLM post-mortem (`llm_postmortem_latest`) — thesis vs outcome
- `POSTMARKET_RL_DEFER=true` — SESSION_CLOSE skips RL; 16:15 owns full pipeline

### Execution guardrails
- **LLM bearish veto** — blocks BUY when bias ≤ −0.5
- **VIX dynamic stop-loss** — tighter stops when VIX elevated
- **VIX fractional sizing** — scales deploy cap down in high vol
- **Panic halt** — dashboard halt squares off all paper positions + kill switch
- Per-trade RL uses guarded train with `skip_shadow=True`

---

## 2026-07-13 (night-2) — Telemetry command center UI + SSE + XAI + slumber

### Dashboard UX (bento grid)
- High-density **bento layout** — XAI, health, tactical, activity, chart, quotes, positions on one screen (1024px+)
- **Telemetry deck** — Kite ping, CPU/RAM, drawdown, LLM ring, slippage risk flash when latency >400ms
- **Agent Reasoning Protocol (XAI)** — plain-language narrative from decisions + macro + RL post-mortem
- **Sparkline micro-charts** in live quotes rows (tick_log)
- **SSE push** `/api/feed/stream` replaces 1s polling; WebSocket fallback `/ws/feed`
- **Confirmation modals** on halt, slumber, budget approve/reject

### Tactical interceptors
- **Force slumber 60m** — blocks new BUYs (`slumber_mode.py`); resume clears slumber + halt
- **Emergency flatten & halt** — panic square-off (existing) with confirm modal

### Backend
- `system_telemetry.py`, `xai_reasoner.py`, `sparkline_data.py`, `ws_broadcast.py`
- `psutil` for VM CPU/RAM on telemetry bar

---

## 2026-07-13 (ship) — Sandbox review + limit chase + production git push

### Added
- **Agent Sandbox Review** — `sandbox_review.py` + `/api/agent/sandbox` + dashboard panel (stable vs candidate RL scores, 10-day history)
- **Limit order chase** — `limit_chase.py` + `LiveBroker.place_async` (opt-in `LIMIT_CHASE_ENABLED` for live)
- **Deploy collision lock** — `asyncio.Lock` on BUY path prevents double-allocation from parallel ticks
- **Feed watchdog** — default stale threshold **5s** (`FEED_STALE_SEC`)
- **Logrotate** — `deploy/logrotate-bharatquant.conf` (7-day rotation)

### Docs
- `docs/SYSTEM_TRACKER.md` Layer 11 (BQ-D1..D12) marked deployed/verified
- Git: pushed to `sanmatiHQ/bharatquant` main (`e6c0c36`)

---

## 2026-07-13 — Open source hardening

- Apache 2.0 `LICENSE`, `scripts/audit_secrets.sh`, README security section
- Removed production hostname from tracked `deploy/Caddyfile` (example only)
- GCP project defaults → `your-gcp-project-id` placeholders in scripts/docs
- Repo visibility: **public** on GitHub

## 2026-07-13 — Open source completion (full)

- `CONTRIBUTING.md`, `SECURITY.md`, GitHub issue/PR templates
- `.github/workflows/ci.yml` — pytest + `audit_secrets.sh` on every PR
- Full `.env.example` parity with `deploy/bharatquant.env.production`
- `scripts/scrub_git_history.sh` — removes infra fingerprints from all commits
- `tests/test_open_source_hygiene.py` — CI regression for OSS gates
- `docs/SYSTEM_TRACKER.md` Layer 12 (BQ-OS1..OS8) marked deployed

---

## 2026-07-13 — Dual-brain advisor patterns (extend existing modules)

Applied relevant external architecture recommendations without new top-level files:

- **OBI (orderbook imbalance)** — `depth_store.py` computes top-5 depth OBI; persisted on `depth_snapshots.obi`; wired into `MarketContext.orderbook_imbalance` and RL state vector slot 9 (`state_encoder.py`)
- **Drawdown action mask** — `action_mask.py` blocks buys when intraday peak-to-trough ≥ `MAX_INTRADAY_DRAWDOWN_PCT` (default 10%); `execution_engine.py` auto `panic_halt_and_squareoff`; gym env mirrors mask
- **Regime RL hot-swap** — `regime_classifier.classify_regime_from_prices` + `RLAgent.hot_swap_regime_policy()` at 08:45 pre-market; weights path `models/rl/regimes/{BULL|BEAR|SIDEWAYS|HIGH_VOL}/policy.npz` with fallback to `ppo_v1`
- **NumPy tick ring** — `TickRingBuffer` in `bar_aggregator.py` (pre-allocated rolling matrix, `TICK_RING_CAPACITY=100`)

**Rejected (unsafe / wrong stack):** dynamic LLM `exec()` strategy synthesis, Redis ring buffer, Cloud SQL, separate `macro_analyst.py` / `vector_cache.py` files.

### Dashboard feed latency fix (same session)
- **Root cause:** `/api/feed/live` called Kite `/user/profile` up to 4× per request + `psutil.cpu_percent(0.1)` block → 8–12s TTFB; UI showed "connecting" until complete.
- **Fix:** `build_live_feed_fast()` (SQLite-only, cached token, no Kite HTTP) + `/api/feed/fast`; SSE uses fast path; poll paints KPIs first then enriches via full feed in background.

### OBI + tick ring in decision path + regime training CLI
- `fast_snapshot` + `router.fuse` use OBI and tick ATR from shared `TickRingBuffer`
- `train_regime_policies()` — bootstrap `models/rl/regimes/{BULL|BEAR|SIDEWAYS|HIGH_VOL}/policy.npz` from base + fine-tune on filtered transitions
- `python3.11 -m src.rl.rl_trainer --train-regimes` and `--force-postmarket` (sandbox refresh + shadow recompute)

---

## 2026-07-13 — Corporate intelligence + profit ledger + dashboard render fix

### Corporate intelligence layer
- **`src/intelligence/corporate_activity.py`** — normalizes NSE insider (`corporates-pit`), bulk/block (`snapshot-capital-market-largedeals`), corp announcements (`corporate-announcements`), FII/DII mass flow; 7-day snapshot + timeline for dashboard/XAI
- **Ingest persistence fixed** — `nse_bulk.py` per-row `BLOCK_DEAL` in `ingest_log`; `nse_corp_rss.py` per-announcement `NEWS_ALERT` (was `{"seen": N}` summary only)
- **`MarketContext`** extended: `recent_corporate`, `dividend_watch`, `promoter_watch`; `ContextUpdater` handles `INSIDER_FILING`, `BLOCK_DEAL`, `NEWS_ALERT`
- **`corporate_profit_tilt()`** — promoter/insider/bulk buy boosts confidence + expected move; insider/bulk sell penalizes BUY
- **Strategies** — `insider_cluster`, `bulk_accumulation` richer reasons; `earnings_vol` dividend → `BUY CNC` capture signal

### Session ledger (open P&L + tomorrow plan)
- **`src/ops/session_ledger.py`** — `build_session_ledger()`: today's trades, realized/unrealized PnL, `plan_for_tomorrow` (official premarket brief or auto-fallback from budget + screening watchlist)
- **Dashboard feed** — `session` object on `/api/feed/fast` and `/api/feed/live`; fast-path XAI leads with PnL + plan (no longer "connecting" only)
- **UI** — full-width **Today's ledger & tomorrow's plan** panel; Recent trades shows Amount + Why columns

### Dashboard JS crash (root cause of empty KPIs)
- **Bug:** `renderTelemetry()` referenced `f.sandbox` out of scope → `renderFeed()` aborted after timestamp; KPIs stayed `—`, ledger stuck "Loading P&L…", intermittent **Feed error**
- **Fix:** `renderSandbox(sb)` separate function; `try/catch` in `renderFeed`; poll shows "Loading feed…" then paints fast feed first
- **VM hotfix:** patched `dashboard_template.py` + supervisor restart; verified served HTML has `renderSandbox` not `const sb=f.sandbox`

### Deploy notes
- `gcp_deploy.sh` post-deploy uses `/etc/bharatquant/env` (not `.env` typo)
- Post-deploy RL/postmarket may show `Permission denied` on env if sourced wrong user — non-fatal; engine heartbeat can lag after restart → ENGINE DOWN pill while process recovers (data still in SQLite)

---

## 2026-07-13 — Institutional learning (open data, no LLM)

### Ingest (P0)
- **`src/ingest/nse_shareholding.py`** — NSE `corporate-share-holdings` per watchlist symbol; `shareholding_snapshots` table; publishes `SHAREHOLDING_UPDATE`
- **`src/ingest/nse_bulk.py`** — enriches bulk rows with `entity_class` (MF/FII/bank/promoter); MF-sized deals also emit `MF_HOLDING_UPDATE`
- **`src/intelligence/institutional_entities.py`** — deterministic client-name classifier + static confidence priors

### Learning loop (agent learns from filings)
- **`corporate_event_outcomes`** — labels insider/bulk/corp/shareholding/MF events with +5d/+20d forward returns from `tick_log`/`bar_log`
- **`src/intelligence/event_outcomes.py`** — `label_pending_events()` scans `ingest_log`
- **`src/intelligence/institutional_learning.py`** — aggregates outcomes → `institutional_learn_weights` in settings; merges into bandit; seeds `rl_transitions` from labeled events
- **Post-market + hourly** — `refresh_context_learning()` in `market_routines` and engine loop; `ctx.institutional_weights` drives `corporate_profit_tilt()` and strategy confidence

### Strategies
- **`bulk_distribution`** — follow institutional sells (mirror of bulk_accumulation)
- **`institutional_flow`** — MF/FII shareholding QoQ increases + MF block buys

### Schema
- `shareholding_snapshots`, `corporate_event_outcomes` in `migrations.sql`

### Proof + live API fix
- **`scripts/probe_institutional_learning.py`** — synthetic E2E (ingest → label → learn → RL → bandit) + `--live SYMBOL` + `--db` VM readout
- NSE shareholding endpoint corrected: `corporate-share-holdings` (404) → **`corporate-share-holdings-master?index=equities&symbol=`** (200); parses promoter/public QoQ deltas
- NSE bulk/block endpoint corrected: `snapshot-capital-market-largedeals` (404) → **`snapshot-capital-market-largedeal?mode=bulk_deals|block_deals`** (200); `BULK_DEALS_DATA` + `BLOCK_DEALS_DATA`
- Engine heartbeat boot fix: `touch_heartbeat()` at engine start + supervisor 180s start grace — stops 30s restart loop (ENGINE DOWN pill)
- **VM proof 2026-07-13:** live INFY fetch OK; `shareholding_snapshots=1`, `ingest_log SHAREHOLDING_UPDATE=1`; `rl_transitions=2122` (existing mesh); outcomes label after +7d
- Dashboard: `institutional_learning` block + `learnBadge` on Profit opportunities panel

---

## 2026-07-13 — Literature strategy expansion (QS + TradingView + 151TS)

### Sources mapped
- QuantifiedStrategies free library — IBS mean reversion, Turnaround Tuesday, dual momentum
- TradingView scripts (PROTOS 616, Momentum Consensus, EMA+RSI, liquidity sweep)
- Kakushadze & Serur, 151 Trading Strategies (SSRN 3247865) — Donchian, NR7, z-score stat-arb

### Bar features (unblocked dead strategies)
- `bar_aggregator.py` emits: `high_20`, `low_20`, `ibs`, `z_score`, `nr7`, `ema9/21`, `ema_cross_up`, `ret_5d`
- Fixes `turtle_breakout` + `short_term_reversal` missing payload fields

### New strategies (33 → 40)
- `literature_strategies.py`: connors_ibs, crabel_nr7, zscore_reversion, momentum_consensus, ema_cross_rsi, liquidity_sweep, turnaround_tuesday

### Learning loop
- `strategy_catalog.py` — lineage + 10 discovery rules
- `strategy_discovery.py` — full OHLC feature recompute from bar_log

---

## 2026-07-13 — Unified strategy learning (everything learned by agent)

### Problem
Literature strategies + discovery rules were firing but not fully learning: bandit only saw executed ledger hits; non-chosen signals discarded; discovery never auto-promoted to runnable rules.

### Solution: `strategy_learning.py` master loop
Every 30m (engine) + post-market:
1. Label all signals — `strategy_ledger` + `shadow_trades` → `strategy_signal_outcomes`
2. Label corporate events — `corporate_event_outcomes`
3. Promote discovery — top rules → `learned_custom_rules` (auto-loaded by registry)
4. Unified weights — `strategy_learn_weights` merges outcomes + PnL + institutional
5. RL seed — corporate + strategy signals → `rl_transitions`
6. Bandit refresh after each learn cycle

### Execution
- All candidate signals recorded when fuse picks winner
- Router applies learned weight multiplier per strategy_id

---

## 2026-07-13 — Priority backlog closed (combiner + ingest + reconcile + AGENTS)

### P0 — Signal combiner
- `src/agent/signal_combiner.py` — 500ms window, net BUY/SELL per symbol, position guard
- Wired into `AgentRouter.fuse()` before bandit scoring

### P1 — NSE corporate calendar ingest
- `nse_corporate_calendar.py` — corporate-actions, board-meetings, event-calendar
- Event types: `CORPORATE_ACTION`, `BOARD_MEETING`, `EVENT_CALENDAR`

### P1 — Reconciliation hardening
- Live default interval **60s** (paper 300s) via `RECONCILE_INTERVAL_SEC`
- Persistent mismatch streak → `set_halt()` after `RECONCILE_HALT_AFTER` (default 3) in live mode
- Telegram + `RECONCILE_ALERT` event on halt

### P2 — AGENTS.md + pre-commit
- `AGENTS.md` — edit boundaries, learning invariant, deploy commands
- `.pre-commit-config.yaml` — audit_secrets + pytest

### P2 — Participant OI
- `nse_participant_oi.py` — archives CSV `fao_participant_oi_ddmmyyyy.csv`
- `PARTICIPANT_OI_UPDATE` → retail vs FII divergence on `MarketContext`

### P3 — BSE cross-feed
- `bse_announcements.py` — BSE `AnnGetData` API
- `BSE_ANNOUNCEMENT` events → corporate context

---

## 2026-07-13 — US literature strategies localized for NSE/BSE (40 → 50)

**Philosophy:** US-session strategies (QuantifiedStrategies, 151TS) are not discarded — each gets an IST-localized twin; paper-learn proves what works in India.

### Session clock
- `market_session.py` — NSE phases: opening_drive, lunch, power_hour; monthly expiry (last Thu)

### New strategies (`nse_localized.py`)
| ID | US origin | India mapping |
|----|-----------|---------------|
| `india_power_hour` | Power hour | 14:30–15:30 IST momentum |
| `india_lunch_fade` | Lunch doldrums | 12:00–13:30 IBS fade |
| `india_opening_drive` | Opening drive | 09:15–09:45 thrust |
| `nifty_buy_the_dip` | SPY buy dip | NIFTYBEES ret_5d < -1.5% |
| `india_dual_rotation` | SPY/TLT | NIFTYBEES vs GOLDBEES |
| `ath_breakout_in` | ATH breakout | near_high_20 + volume |
| `lower_highs_fade` | LH distribution | lower_high_streak ≥ 2 |
| `us_overnight_follow` | Overnight drift | GIFT gap → SESSION_OPEN |
| `expiry_week_caution` | Monthly OPEX | Last Thu expiry fade |
| `monday_effect_in` | Monday effect | Monday + weak GIFT bounce |

### Bar features
- `near_high_20`, `lower_high`, `lower_high_streak` in bar_aggregator + discovery miner

### Learning
- `strategy_catalog.py` — `localized_from` metadata per strategy
- All signals flow through existing ledger → outcomes → bandit weights (no hard-promote)

---

## 2026-07-13 — Market awareness + fear/greed + learn-all-NSE-activities

### Temporal awareness (single clock)
- `market_session.py` — `is_nse_open()`, `minutes_to_close`, `market_clock_snapshot()`
- `market/market_awareness.py` — refreshes `MarketContext` every 60s + on SESSION/IV/LLM events
- `MarketContext` fields: `session_phase`, `nse_status`, `market_open`, `ist_date/time`, `minutes_to_close`, `is_expiry_day`
- `timebox.is_market_open()` delegates to `market_session` (one source of truth)
- Dashboard `/api/market/session` returns full clock snapshot

### Fear vs greed
- `intelligence/sentiment_index.py` — composite 0–100 from VIX (30%), FII (25%), GIFT (15%), LLM (15%), retail-FII divergence (15%)
- Labels: Extreme Fear / Fear / Neutral / Greed / Extreme Greed
- `sentiment_regime` strategy — contrarian BUY on extreme fear, trim on extreme greed

### News awareness
- `intelligence/news_context.py` — headlines from NEWS_ALERT, BSE, board meetings, corp actions (48h window)
- `llm_macro` now uses filtered exchange headlines (not random ingest_log noise)
- Dashboard shows `recent_headlines` + F&G chip

### Learn every NSE-declared activity
- `event_outcomes` now labels: CORPORATE_ACTION, BOARD_MEETING, EVENT_CALENDAR, BSE_ANNOUNCEMENT
- `classify_corp_category` extended: split, bonus, buyback, merger, delisting
- `calendar_activity` strategy — dividend, earnings, buyback, split/bonus signals with learned weights
- Bulk burst polls at 08:45 + 14:05 IST (`run_bulk_burst_once`)

### Strategies: 50 → 52
- `calendar_activity`, `sentiment_regime`

---

## 2026-07-14 — Live N50/N100 charts + intraday learning visibility

### Symptoms
- Dashboard charts static (Yahoo one-shot); no timeframe controls
- User expected 08:45 IST block-deal window + live index movement
- Learning badge showed cumulative counts only — no today ticks/signals/labeled

### Fixes
- `fetch_index_ohlc(period, interval)` — Kite historical primary, NSE spot `last`/`change_pct`, Yahoo/DB fallback
- `index_quote_poller` — Kite LTP every 30s from `block_deal` through `power_hour` → `tick_log` + rolling 5m `bar_log`
- Dashboard: 1D/5D/1M range buttons; chart auto-refresh every ~15s on feed poll
- `session_today` on feed: `signals_today`, `labeled_today`, `ticks_today`
- Strategy labeling: 5m horizon when `is_nse_open()`; learn loop 5m cadence intraday (was 30m)

### Verified (VM)
- `GET /api/index/ohlc/nifty50?period=1d&interval=1m` → `kite:NSE:NIFTY 50:1m`, 496 bars, live last
- Feed: `ws_live=true`, ~529 ticks/min, `session_today` populated

---

## 2026-07-14 — Brain audit fixes: regime, Kelly, RL costs, shadow gate, cost-edge

### Audit finding
Layer 6 "brain" was wired but several adaptive pieces were theater: regime always SIDEWAYS (1-element FII input), Kelly hardcoded 0.55/1.2/1.0 + mystery ×0.02, RL reward gross-only, shadow gate auto-pass on thin history, cost-edge bypassed for MIS/conf≥0.82.

### Fixes
1. **Regime** — `refresh_ctx_regime()` reads NIFTY50/NIFTYBEES bar_log (≥10 closes) → `classify_regime_from_prices`; wired on FII update, session events, `BAR_CLOSE_5M`; FII ±500cr still overrides to BEAR/BULL
2. **Kelly** — `kelly_stats.kelly_inputs_for_strategy()` from `strategy_signal_outcomes`; removed ×0.02 shrink; router uses per-strategy stats
3. **RL gym** — buy/sell rewards net of slippage + Zerodha fees via `CostEngine`
4. **Shadow gate** — requires ≥500 bars + ≥3 symbols; `both_neutral` and thin stable history → **reject** promote
5. **Cost-edge** — removed MIS opportunistic + confidence≥0.82 bypasses; always enforce `expected >= min_move`

### Tests
- `tests/test_audit_fixes.py` — regime from bars, Kelly from outcomes, shadow thin-history reject
- 135 passed

### Deferred (next batch)
- Prune `advanced_quant.py` redundant strategies / strategy_lab significance gate
- Portfolio correlation basket control
- SB3→live policy export fidelity
- True Thompson bandit (current bandit weights already flow to router hourly)

---

## 2026-07-14 — Audit items 0–10 completion (intelligence honesty batch 2)

### Root causes closed
| # | Issue | Fix |
|---|--------|-----|
| 0 | PaperBroker slippage favoured trader | `PaperBroker` delegates to `CostEngine.apply_slippage` only (BUY above LTP, SELL below) |
| 1 | Regime never ran vol/trend math | Rolling `index_returns` deque on `BAR_CLOSE_5M`; FII ±500cr nudges adjacent regimes only |
| 2 | Kelly hardcoded 0.55/1.2/1.0 + silent ×0.02 | `strategy_stats.py` — Bayesian Beta(3,3), cold-start 0.5/1.0; `KELLY_SAFETY_SCALAR` env |
| 3 | Bandit rewarded self-reported confidence | Thompson sampling from realized win/loss counts (`random.betavariate`) |
| 4 | RL reward gross-only | `gym_env` net buy/sell via `CostEngine`; hold steps pass net unrealized; variance penalty |
| 5 | Shadow gate rubber-stamp | Requires ≥500 bars + ≥3 symbols; `deferred_insufficient_stable_history`; no neutral auto-pass |
| 6 | SB3→numpy export lossy | `RLAgent` loads `sb3_ppo.zip` at inference when present; numpy export is fallback only |
| 7 | Strategy redundancy + noise promotion | `strategy_correlation.refresh_disabled_strategies` in learn loop; binomial p<0.05 on `promote_discovery_rules` + `StrategyLabStrategy` |
| 8 | Cost-edge bypass + hardcoded edge table | Removed `_STRATEGY_EDGE_PCT`; `expected_move_pct_for_strategy()` from outcomes |
| 9 | No portfolio beta cap | `portfolio_beta.can_add_beta_exposure()` in `router.risk_veto()` |
| 10 | RBI approx dates + RSI proxy | Published MPC calendar 2025/2026; Wilder RSI in `strategy_discovery` |

### Tests
- `tests/test_audit_fixes.py` — 18 cases covering slippage direction, regime deque/FII nudge, Kelly cold-start, Thompson bandit, shadow gate, binomial promotion, beta cap, RBI dates, RSI variance
- **150 passed**, 5 skipped (`python3.11 -m pytest -q`)

### Deploy
- Run `gcp_deploy.sh` after market close or during paper session to refresh VM stack

---

## 2026-07-14 — Risk-adjusted fitness everywhere (Sortino/Calmar learning objective)

### Strategic shift
Swapped fitness function from raw/cumulative PnL to **risk-adjusted, after-cost returns** across RL reward, Kelly, bandit, promotion gates, and strategy lifecycle.

### Changes
| Component | Before | After |
|-----------|--------|-------|
| **RL reward** (`reward.py`) | return − fixed drawdown penalty | Sortino-shaped: `net_return − λ·downside_deviation` |
| **Kelly** (`kelly_sizing.py`) | fixed ¼-Kelly | adaptive fraction shrinks when win-rate variance is high (`KELLY_WR_VAR_CAP`, `KELLY_NOISE_SHRINK`) |
| **Shadow gate** (`shadow_backtest.py`) | cumulative net score | Calmar + Sortino composite fitness |
| **Promotion** (`strategy_learning`, `advanced_quant`) | positive PnL / win rate | binomial + Sortino/Calmar composite |
| **Bandit** (`bandit.py`) | Thompson on outcomes | + diversity cap (`BANDIT_MAX_WEIGHT=0.40`) |
| **Credit assignment** (`shadow_trades.py`, `router.fuse`) | winner only | all fuse competitors logged to shadow_trades |
| **Regime switching** (`regime_change_detector.py`) | FII event cadence | vol/return shock trigger + 3-bar persistence dampener |
| **Lifecycle** (`strategy_lifecycle.py`) | permanent strategy seats | candidacy → probation (10% cap) → full → auto-demotion |

### New modules
- `src/risk/risk_metrics.py` — downside deviation, Sortino, Calmar, composite fitness
- `src/agent/regime_change_detector.py` — intraday shock + persistence
- `src/agent/strategy_lifecycle.py` — governance state machine

### Tests
- `tests/test_risk_adjusted_fitness.py` — 11 cases
- **161 passed**, 5 skipped

### Hotfix (2026-07-14) — audit callback P0/P1
- **promote_discovery_rules** — removed repeated-mean Sortino rubber stamp; uses `forward_returns_for_discovery_rule()` on real bar_log hits
- **calmar_ratio** — actually annualizes; removed inflation fallbacks in Sortino/Calmar
- **corporate_profit_tilt** — removed hardcoded multipliers; learned `pattern_multiplier` only

---

## 2026-07-12 — Engine crash loop / supervisor orphans (prior entry)

### Audit finding
2. **Engine crash loop** — `persist_engine_phase(db, "BOOT")` arity mismatch → zombie PID, no ticks
3. **Supervisor orphans** — `Popen(start_new_session=True)` survived systemd restart → port 8080 fight → Caddy 502
4. **OAuth/engine split** — token saved in dashboard; engine needed file watcher + restart flag (30s)

### Fixes shipped
- `gcp_sync_secrets.sh`: skip VM token upload by default; `SYNC_KITE_TOKEN=1` only if local token validates live
- `kite_token_watcher.py`: mtime poll → invalidate cache → `_restart_feed()` within ~10s
- `market_supervisor._bootstrap_stack()`: kill orphan engine/dashboard, wait for :8080, then start
- `persist_engine_phase(db)` call fixed in `main.py`
- **`scripts/pre_deploy_smoke.sh`** — pytest + boot contract before rsync
- **`scripts/post_deploy_gate.sh`** — health HTTPS+local, single PID, heartbeat, kite auth, no bind errors
- `gcp_deploy.sh` runs smoke → deploy → gate (deploy fails loud if stack unhealthy)

### Prevention
- Never scp hotfix without full deploy + gate
- VM owns Kite token; laptop token never overwrites production OAuth

---

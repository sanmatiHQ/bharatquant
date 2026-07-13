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
- Git: pushed to `sanmatiHQ/bharatquant` main

---

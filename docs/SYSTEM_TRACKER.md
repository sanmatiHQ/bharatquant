# BharatQuant — System Tracker

> **Purpose:** Single checklist for what must be **built**, **verified**, and **deployed**.  
> **Status:** `open` | `in_progress` | `verified` | `deployed` | `deferred`  
> **Done = `verified` + `deployed` on GCE with real-data proof log** — not code exists.  
> **Tracker:** `docs/SYSTEM_TRACKER.md` · **History:** `docs/EVOLUTION_LOG.md` · **Code:** `zerodha-momo-rl/`

---

## Deploy policy (inviolable — owner 2026-07-14)

**Order:** Read → Probe → **Test** (pytest) → **Prove** (E2E / real-data log) → **Deploy** (`gcp_deploy.sh` only).

| Step | Gate | Block deploy if |
|------|------|-----------------|
| **Test** | `python3.11 -m pytest` green | Any failure |
| **Prove** | Item-specific deploy gate in layer table + EVOLUTION_LOG snippet | No proof log |
| **Deploy** | `bash scripts/gcp_deploy.sh` end-to-end | `pre_deploy_smoke.sh` fails |
| **Post** | `post_deploy_gate.sh` ALL PASS | Health / PID / Kite / HTTPS red |

**Forbidden:** manual rsync/tar when automated gate fails; marking `deployed` from changelog trust; deploying capital-risk changes without independent diff review.

**Go-live clock** (EVOLUTION_LOG § Hotfix 2): 6 clean paper weeks, ≥150 trades, composite ≥0.5, max DD ≤18% — **measurement only until gates pass**; not a deploy trigger.

---

## Layer summary (honest — 2026-07-14)

| Layer | Name | Built (code) | Verified (pytest) | Deployed (VM proof) |
|-------|------|--------------|-------------------|---------------------|
| 0 | Foundation | partial | partial | partial |
| 1 | Cloud infra | yes | smoke only | **yes** (GCE + systemd + HTTPS) |
| 2 | Auth & connectivity | yes | partial | **partial** (OAuth token; ticks live) |
| 3 | Event engine | yes | partial | partial |
| 4 | Data ingestion | partial | partial | **partial** (NSE corp/bulk/insider) |
| 5 | Strategy registry | yes (52+) | partial | **not proven** (no 6w paper) |
| 6 | Agent brain | yes | **yes** (161 pytest) | **not proven** (pre-fix paper contaminated) |
| 7 | Execution rails | yes | partial | partial (paper at real LTP) |
| 8 | Risk & compliance | partial | partial | partial |
| 9 | UI & observability | yes | partial | partial (dashboard live) |
| 10 | Backtest & proof | walk-forward verified | partial | **open** (BQ-C1 clock not started clean) |
| 11 | Autonomy command center | yes | partial | **code on VM — PnL proof invalid pre-fix** |
| 12 | Open source | yes | **yes** (165 pytest + audit) | **yes** (scrub + force-push 1120347) |
| CHERRY | Quant pickups | 8 verified | yes | partial |

**Tracker drift:** Many Layer 6 rows still say `open` though code + tests exist — status means **not deploy-proven**, not "not built". Layer 11 `deployed` rows mean **code rsync'd to VM**, not go-live ready.

---

## Charter

| Field | Value |
|-------|-------|
| Name | BharatQuant (working) |
| Mission | 100% autonomous event-driven trading agent — NSE/BSE execution via Kite; GIFT/regime/sentiment as signals |
| KPI | Net P&L after STT, brokerage, STCG/LTCG; strategy-attributed Sharpe; max drawdown; uptime |
| Runtime | GCP GCE only — static IP, no local |
| Intelligence | Statistical + optional Gemini Flash (research only) — **never** LLM on order path |
| Week 1 target | Day 7: paper-proven daemon + live enabled with hard caps |

---

## Layer 0 — Foundation & hygiene

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-00 | Git repo + `.gitignore` (secrets, venv, tokens) | deployed | — | Public repo + `audit_secrets.sh` green |
| BQ-01 | Rename / restructure → `src/` event-native layout | in_progress | BQ-00 | No `scheduler.py` trading cron |
| BQ-02 | Delete all dummy/placeholder data paths | in_progress | BQ-01 | `rg "dummy\|placeholder\|ltp = 100" src/` empty |
| BQ-03 | `config.yaml` + env + Secret Manager contract | in_progress | BQ-00 | All secrets off disk |
| BQ-04 | Structured JSON logging → Cloud Logging | open | BQ-03 | Log line in Cloud Console |
| BQ-05 | Python 3.11 venv on VM (not 3.9 local venv) | open | BQ-03 | `python3.11 --version` on VM |

---

## Layer 1 — Cloud infrastructure (GCP only)

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-10 | GCE e2-small `asia-south1` | deployed | — | SSH works |
| BQ-11 | Static external IP attached | deployed | BQ-10 | IP documented |
| BQ-12 | Zerodha Kite API IP whitelist | deployed | BQ-11 | Broker confirmation |
| BQ-13 | 20GB persistent disk `/var/lib/bharatquant/` | deployed | BQ-10 | SQLite path writable |
| BQ-14 | GCP Secret Manager (Kite, TOTP, password, Gemini) | in_progress | BQ-10 | `gcloud secrets versions access` |
| BQ-15 | GCS bucket nightly SQLite backup | in_progress | BQ-13 | Object in bucket after `SESSION_CLOSE` event |
| BQ-16 | systemd `bharatquant-engine` Restart=always | deployed | BQ-10 | `systemctl is-active` |
| BQ-17 | systemd `bharatquant-api` (FastAPI :8080) | deployed | BQ-16 | `curl /health` 200 |
| BQ-18 | Deploy script `git pull` + restart | verified | BQ-16 | `gcp_deploy.sh` — **must pass smoke; no manual rsync** |
| BQ-19 | Ops: non-trading health ping only | open | BQ-17 | Uptime alert fires on kill |

---

## Layer 2 — Auth & connectivity (autonomous)

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-20 | Headless Kite TOTP login (Playwright + pyotp) | open | BQ-14 | `token_persisted` without browser |
| BQ-21 | `TOKEN_EXPIRED` / `WS_AUTH_FAIL` → auto re-auth | open | BQ-20 | Simulated 403 → recovery log |
| BQ-22 | Kite REST client (rate limit + retry) | open | BQ-20 | Real LTP for 3 symbols |
| BQ-23 | Kite WebSocket tick stream | in_progress | BQ-20 | `TICK` events in log 09:15–15:30 |
| BQ-24 | Instrument token map (universe ↔ token) | in_progress | BQ-22 | **2,335** main-board symbols (`universe_full_nse.csv`) |
| BQ-25 | SEBI order throttle ≤10 OPS token bucket | verified | BQ-22 | `LiveBroker` RateLimiter 10/sec |

---

## Layer 3 — Event engine (core — no trading cron)

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-30 | `EventBus` asyncio — pub/sub | in_progress | BQ-16 | Unit test publish/subscribe |
| BQ-31 | Event types: GIFT_*, NSE_*, TICK, ORDER_FILL, TOKEN_* | in_progress | BQ-30 | Enum documented |
| BQ-32 | Session events from exchange status (not wall clock) | open | BQ-30 | PREOPEN before REGULAR in log |
| BQ-33 | Tick → bar aggregator (5m, 15m, 1d) | open | BQ-23 | BAR_CLOSE fires on tick boundary |
| BQ-34 | `STOP_BREACH` on every position TICK | open | BQ-23, BQ-60 | Paper sell <1s after breach |
| BQ-35 | `SESSION_CLOSE` → MIS square-off chain | open | BQ-34 | No overnight MIS in DB |
| BQ-36 | Feed watchdog (staleness → reconnect, not strategy timer) | open | BQ-23 | WS drop → reconnect log |

---

## Layer 4 — Data ingestion (real feeds only)

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-40 | GIFT Nifty tick/poll → `GIFT_TICK` (signal only) | open | BQ-30 | Real price ≠ null 06:30 |
| BQ-41 | NSE block deals → `BLOCK_DEAL` | deployed | BQ-30 | Per-row `ingest_log` + `nse_bulk.py` |
| BQ-42 | NSE bulk deals ingest | deployed | BQ-41 | Same API snapshot; normalized in `corporate_activity` |
| BQ-43 | NSE insider trades → `INSIDER_FILING` | deployed | BQ-30 | `corporates-pit` poller + profit tilt |
| BQ-44 | FII/DII on publish → `FII_DII_UPDATE` | open | BQ-30 | Real ₹ Cr from NSE |
| BQ-45 | NSE pre-open indicative → `PREOPEN_PRICE` | open | BQ-22 | Price 09:00–09:15 |
| BQ-46 | India VIX feed | open | BQ-22 | Live VIX in context |
| BQ-47 | Kite option chain + IV → `IV_UPDATE` | open | BQ-22 | Chain for NIFTY |
| BQ-48 | Delivery % (NSE) — India-specific | open | BQ-41 | deferred W2 if API hard |
| BQ-49 | Global: US fut, crude, USDINR (1m poll) | open | BQ-30 | Values update overnight |
| BQ-50 | NSE corp announcements RSS | deployed | BQ-30 | Per-row `NEWS_ALERT`; dividend/promoter classifier |
| BQ-51 | Screener.in fundamentals (quality factor) | open | BQ-22 | ROE for 5 symbols |
| BQ-52 | ASM/GSM / F&O ban universe filter | open | BQ-24 | Banned symbol rejected |

---

## Layer 5 — Strategy plugin registry (1 → N)

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-60 | `Strategy` protocol + YAML registry | open | BQ-30 | Add strategy without code deploy |
| BQ-61 | Cross-sectional momentum (Jegadeesh-Titman) | in_progress | BQ-60, BQ-22 | Real signal log |
| BQ-62 | Opening range breakout (event-bound) | open | BQ-33 | Signal on range break TICK |
| BQ-63 | Turtle / Donchian breakout | open | BQ-61 | — |
| BQ-64 | VWAP mean reversion (MIS) | open | BQ-33 | — |
| BQ-65 | FII-DII regime gate | open | BQ-44 | NO_TRADE on extreme FII sell |
| BQ-66 | Bulk deal accumulation follow | open | BQ-42 | — |
| BQ-67 | Insider cluster (promoter buys) | open | BQ-43 | — |
| BQ-68 | Pairs stat arb (cointegration) | open | BQ-61 | deferred W2 |
| BQ-69 | IV rank premium sell (covered call / condor) | open | BQ-47 | — |
| BQ-70 | Earnings / results vol event | open | BQ-50 | — |
| BQ-71 | GIFT gap follow/fade | open | BQ-40 | Signal before 09:15 |
| BQ-72 | Quality + momentum (AQR-style) | open | BQ-51 | — |
| BQ-73 | Cash-futures basis arb | open | BQ-47 | deferred W2 |
| BQ-74 | Expiry gamma / OI pinning | open | BQ-47 | deferred W2 |
| BQ-75 | Global risk beta filter | open | BQ-49 | — |

---

## Layer 6 — Agent brain (no LLM execution)

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-80 | Regime classifier (HMM: BULL/BEAR/SIDEWAYS/HIGH_VOL) | verified | BQ-44, BQ-46 | Regime tag per day |
| BQ-81 | Strategy router — regime → whitelist | verified | BQ-60, BQ-80 | Wrong regime → strategy silent |
| BQ-82 | Bayesian signal fusion → confidence | in_progress | BQ-81 | Score 0–1 on each signal |
| BQ-83 | Kelly / fractional Kelly sizing (capped) | verified | BQ-82 | Position size in log |
| BQ-84 | VaR + max drawdown circuit breaker | verified | BQ-83 | Halt on breach |
| BQ-85 | Nightly bandit — strategy weight update | verified | BQ-90 | Weights change after P&L |
| BQ-86 | Shadow trades (predict without execute) | verified | BQ-90 | Calibration table |
| BQ-87 | Optional Gemini Flash — news/earnings only | open | BQ-50 | ≤50 calls/day cap |
| BQ-88 | Decision log — every signal with reason | open | BQ-82 | JSON audit trail |

---

## Layer 7 — Execution rails (Kite)

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-90 | `strategy_ledger` + FIFO lots in SQLite | verified | BQ-13 | Round-trip P&L correct |
| BQ-91 | Paper broker — real LTP + slippage bps | verified | BQ-23 | Fill price = Kite LTP ± slip |
| BQ-92 | CNC (delivery) executor | open | BQ-91 | Paper BUY/SELL logged |
| BQ-93 | MIS (intraday) executor | open | BQ-91, BQ-35 | Same-day close |
| BQ-94 | NRML (F&O futures) executor | open | BQ-91 | Margin check |
| BQ-95 | OPT (CE/PE) executor + greeks gate | open | BQ-94, BQ-47 | Defined-risk only |
| BQ-96 | Live broker `place_order` path | open | BQ-92–95 | Disabled until flag |
| BQ-97 | `trading.mode: paper \| live` config flag | open | BQ-96 | Live blocked in paper |
| BQ-98 | Cost engine — STT, brokerage, GST, STCG/LTCG | verified | BQ-90 | Known trade → correct tax |
| BQ-99 | Margin pre-check on every signal | open | BQ-22 | Reject if insufficient |

---

## Layer 8 — Risk & compliance (SEBI 2026)

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-A0 | Static IP only API access | open | BQ-12 | No open API |
| BQ-A1 | Per-order exchange tag / audit ID | open | BQ-96 | Log matches broker |
| BQ-A2 | Daily loss halt (₹ configurable) | open | BQ-84 | Trading stops on breach |
| BQ-A3 | Per-trade max size (₹ configurable) | open | BQ-83 | Order rejected above cap |
| BQ-A4 | Max open positions + sector concentration | open | BQ-83 | — |
| BQ-A5 | Event calendar — RBI, expiry, budget → risk down | open | BQ-80 | No new MIS on RBI day |
| BQ-A6 | Kill switch API `POST /internal/halt` | verified | BQ-17 | `src/ops/kill_switch.py` + dashboard |
| BQ-A7 | ASM/GSM stage exclusion | open | BQ-52 | — |

---

## Layer 9 — UI & observability

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-B0 | FastAPI replaces Flask | open | BQ-17 | All routes real data or 503 |
| BQ-B1 | Dashboard — portfolio, P&L after tax | deployed | BQ-B0 | Session ledger + KPIs on fast feed |
| BQ-B2 | TradingView Lightweight Charts — OHLC | open | BQ-B0, BQ-22 | Real candles |
| BQ-B3 | Trade markers on chart | open | BQ-B2 | BUY/SELL visible |
| BQ-B4 | GIFT vs Nifty gap panel | open | BQ-40 | Live spread |
| BQ-B5 | FII/DII chart | open | BQ-44 | — |
| BQ-B6 | Per-strategy P&L breakdown | open | BQ-90 | — |
| BQ-B7 | Telegram alerts — trade, halt, auth fail | open | BQ-16 | Message received |
| BQ-B8 | Daily after-tax summary (automated) | open | BQ-98 | — |

---

## Layer 10 — Backtest & proof

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-C0 | Walk-forward backtest = same code path as live | verified | BQ-60 | `walk_forward.py` + FeatureStore |
| BQ-C1 | Paper run continuous Days 1–6 | in_progress | BQ-30–99 | 6 days `strategy_ledger` — **clock reset 2026-07-14 post fitness fix** |
| BQ-C2 | Day 7 live enable + caps | open | BQ-C1, BQ-96 | User caps in config |
| BQ-C3 | Rolling Sharpe / max DD dashboard | open | BQ-C1 | deferred post-W1 |

---

## Deploy checklist (Day 7 go-live)

```
[ ] BQ-10..19  VM + secrets + systemd on GCE
[ ] BQ-20..25  TOTP auth + WebSocket ticks (real)
[ ] BQ-30..36  EventBus — zero trading cron in codebase
[ ] BQ-40..46  GIFT + NSE institutional feeds live
[ ] BQ-60+     ≥1 strategy firing on real events
[ ] BQ-90..99  Paper fills at real LTP; costs applied
[ ] BQ-A0..A7  Risk caps configured (₹/trade, daily loss)
[ ] BQ-B0..B7  Dashboard + Telegram working
[ ] BQ-02      No dummy/placeholder paths remain
[ ] BQ-97      trading.mode = live ONLY after checklist green
```

---

## Week 1 sprint map

| Day | Tracker IDs (primary) |
|-----|------------------------|
| **1** | BQ-00–05, 10–14, 20–24, 30–32, 02 |
| **2** | BQ-23–25, 33–34, 60–61, 90–92, 98 |
| **3** | BQ-40–46, 65–67, 71, 80–82 |
| **4** | BQ-62–64, 45, B0–B2 |
| **5** | BQ-47, 69, 93–95, 35, B3–B5 |
| **6** | BQ-15–19, 84–88, B6–B8, 68 deferred |
| **7** | BQ-C1–C2, 96–97, deploy checklist |

---

## Global platform capability matrix (target state)

| Capability | Bloomberg | IBKR | QuantConnect | **BharatQuant target** |
|------------|-----------|------|--------------|------------------------|
| Multi-asset execution | ✅ | ✅ | ✅ | CNC/MIS/NRML/OPT |
| Real-time ticks | ✅ | ✅ | ✅ | Kite WebSocket |
| Event-driven algos | ✅ | ✅ | ✅ | EventBus |
| Pre-market / global bias | ✅ | ✅ | Partial | GIFT from 06:15 |
| Institutional flow | ✅ | Partial | ❌ | FII/DII, bulk, insider |
| Options analytics | ✅ | ✅ | ✅ | IV rank, greeks |
| Paper = live parity | Partial | ✅ | ✅ | Paper at real LTP |
| Risk / kill switch | ✅ | ✅ | ✅ | BQ-A* layer |
| Strategy plugins | ❌ | ✅ | ✅ | YAML registry |
| Cloud autonomous | ❌ | Partial | ✅ | GCE 100% |
| India tax in P&L | ❌ | Partial | ❌ | STCG/LTCG engine |
| LLM research | ✅ | ❌ | ❌ | Optional Gemini |
| Cost (retail) | $$$$ | $ | $ | ~₹1,150/mo |

---

## Deferred (post Week 1)

| ID | Item | Reason |
|----|------|--------|
| BQ-48 | Delivery % | NSE scrape complexity |
| BQ-68 | Pairs arb | Needs cointegration calibration |
| BQ-73 | Cash-fut basis | W2 F&O depth |
| BQ-74 | Gamma pinning | Expiry-week only |
| BQ-C3 | Sharpe dashboard | Needs 30d paper data |
| — | BSE parallel venue | Low edge for v1 |
| — | MCX commodities | Separate margin model |
| — | Zerodha GTT automation | Nice-to-have |

---

## Layer CHERRY — Quant repo pickups (2026-07-12 audit)

> Source: 40+ GitHub QuantFinance repos.user audit. Full matrix: `docs/EVOLUTION_LOG.md` Session cherry-pick.

| ID | Pickup | From | Status | Phase |
|----|--------|------|--------|-------|
| BQ-CHERRY-01 | Tick + bar recorder → SQLite (vnpy `data_recorder`) | vnpy | verified | W1 |
| BQ-CHERRY-02 | skfolio portfolio weights on screened top-N | optimizer | verified | W1 |
| BQ-CHERRY-03 | Ingest provenance (`source`, `fetched_at`, `execution_allowed`) | QuantFinance-Databases | verified | W1 |
| BQ-CHERRY-04 | Walk-forward backtest CLI (Kite OHLC + costs vs NIFTYBEES) | rqalpha + trading-bot | verified | W2 |
| BQ-CHERRY-05 | Signed Telegram/webhook alerts + delivery_id | signal-automation | verified | W1 |
| BQ-CHERRY-06 | Gemini research agent (debate UI, no orders) | TradingAgents-AShare | deferred | W3 |
| BQ-CHERRY-07 | akshare supplemental India fundamentals ingest | akshare | verified | W1 — optional dep `akshare_fii.py` |
| BQ-CHERRY-08 | TA feature library (RSI/MACD/BB from Finance repos) | shashankvemuri/Finance | verified | W1 |
| BQ-CHERRY-REJECT | yfinance/wallstreet as execution feed | — | **rejected** | — |
| BQ-CHERRY-REJECT | Full qlib / vnpy framework replace | — | **rejected** | — |
| BQ-CHERRY-REJECT | DQN/RL live trading | — | **rejected** | — |

---

## Layer 11 — Autonomy command center (2026-07-13)

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-D1 | Pre-market routine 08:45 IST (LLM + budget VIX gate) | deployed | BQ-30 | `premarket_brief_latest` in settings |
| BQ-D2 | Post-market routine 16:15 (slippage + RL + post-mortem) | deployed | BQ-C0 | `rl_last_train_meta` after close |
| BQ-D3 | RL guardrails (low LR + 30d shadow backtest promote) | deployed | BQ-C0 | Revert log on regression |
| BQ-D4 | Budget accumulate + daily stipend (no reset) | deployed | BQ-90 | Pool rolls forward |
| BQ-D5 | VIX dynamic stop + fractional sizing + LLM bearish veto | deployed | BQ-46 | VETO logs in ledger |
| BQ-D6 | Telemetry command center (bento + SSE + XAI panel) | deployed | BQ-B0 | `/api/feed/stream` live |
| BQ-D7 | Slumber mode + panic flatten + confirm modals | deployed | BQ-A6 | `/api/slumber` owner |
| BQ-D8 | Agent Sandbox Review (shadow RL scores + history) | deployed | BQ-D3 | `/api/agent/sandbox` |
| BQ-D9 | Limit order chase (live mode, opt-in) | verified | BQ-96 | `LIMIT_CHASE_ENABLED=true` |
| BQ-D10 | Feed stale reconnect 5s + deploy asyncio lock | deployed | BQ-36 | Reconnect on FEED_STALE |
| BQ-D11 | Logrotate 7d on VM | verified | BQ-10 | `deploy/logrotate-bharatquant.conf` |
| BQ-D12 | Full NSE universe screen (~58 names) | deployed | BQ-24 | `screening_results` >20 |
| BQ-D13 | Orderbook imbalance (OBI) in RL state + depth store | verified | BQ-36 | `depth_snapshots.obi` populated |
| BQ-D14 | Intraday drawdown circuit breaker (10% default) | verified | BQ-A6 | `intraday_drawdown_halt` log |
| BQ-D15 | Regime-isolated RL policy hot-swap (08:45) | verified | BQ-D1 | `rl_regime_hot_swap` log |
| BQ-D16 | NumPy tick ring buffer (vectorized micro features) | verified | BQ-36 | `TickRingBuffer` on bar agg |
| BQ-D17 | Corporate intelligence layer (insider/bulk/corp RSS + FII mass flow) | deployed | BQ-41–43, BQ-50 | `corporate_activity.py` + `ingest_log` per row |
| BQ-D18 | Profit tilt — corporate cues → confidence + cost-edge expected move | deployed | BQ-D17 | `corporate_profit_tilt()` in router/fast_snapshot |
| BQ-D19 | Session ledger — trades, PnL, tomorrow plan on fast feed | deployed | BQ-D6 | `session` in `/api/feed/fast` |
| BQ-D20 | Dashboard render fix (`renderSandbox` JS crash) | deployed | BQ-D6 | KPIs populate after hard refresh |
| BQ-D21 | NSE shareholding pattern ingest (promoter/FII/DII/MF %) | deployed | BQ-D17 | `nse_shareholding.py` daily poll |
| BQ-D22 | MF/bulk client classifier (MF/FII/bank/promoter) | deployed | BQ-D21 | `institutional_entities.py` |
| BQ-D23 | Corporate event outcome labeler (+5d/+20d returns) | deployed | BQ-D17 | `corporate_event_outcomes` table |
| BQ-D24 | Institutional learning loop (bandit + RL seed, no LLM) | deployed | BQ-D23 | `institutional_learning.py` hourly + postmarket |
| BQ-D25 | Strategies `bulk_distribution` + `institutional_flow` | deployed | BQ-D22 | Registry + learned confidence boost |

---

## Layer 12 — Open source (2026-07-13)

| ID | Component | Status | Depends | Deploy gate |
|----|-----------|--------|---------|-------------|
| BQ-OS1 | Apache 2.0 LICENSE | deployed | BQ-00 | `LICENSE` in repo |
| BQ-OS2 | Public GitHub repo | deployed | BQ-OS1 | `visibility=PUBLIC` |
| BQ-OS3 | Secret audit script | deployed | BQ-OS1 | `bash scripts/audit_secrets.sh` exit 0 |
| BQ-OS4 | Full `.env.example` (parity with production template) | deployed | BQ-03 | All `__PLACEHOLDER__` keys documented |
| BQ-OS5 | CONTRIBUTING + SECURITY + issue/PR templates | deployed | BQ-OS2 | Community health files present |
| BQ-OS6 | GitHub Actions CI (pytest + audit) | deployed | BQ-OS3 | `.github/workflows/ci.yml` green |
| BQ-OS7 | Git history infra scrub | deployed | BQ-OS3 | `scrub_git_history.sh` + `pre_deploy_smoke` PASS (1120347) |
| BQ-OS8 | Infra placeholders in tracked tree | deployed | BQ-OS3 | No production VM IP / hostname in `git ls-files` |

---

*Update status on every verified milestone. Do not mark `deployed` without Cloud Logging proof snippet in EVOLUTION_LOG.*

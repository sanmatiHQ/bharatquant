# BharatQuant — autonomous NSE trading (event-driven)

**No manual data. No fake OHLC. No cron trading.**

See **[CHANGELOG.md](CHANGELOG.md)** for full session history (2026-07-13: budget gate, real holdings, 30 strategies, dashboard UX).

## Daily budget (hard cap)

| Rule | Detail |
|------|--------|
| Deploy cap | **₹1,500–₹2,000/day** via `DAILY_INVESTMENT_MIN/MAX` (live Zerodha after profitability) |
| Phase 1 | **paper_learn** — real Kite ticks, paper orders, RL on live market |
| Phase 2 | **live_deploy** — set `TRADING_MODE=live` after `LIVE_GATE_MIN_PAPER_RETURN_PCT` met |
| No auto top-up | Paper cash seeds **once** — agent cannot invent money |
| Raise limit | Agent requests via dashboard → you **Approve** within **15 min** or request expires; agent continues with current budget |

## Real portfolio

With Kite token active, the agent syncs your **real Zerodha holdings** and skips paper CNC buys on symbols you already own.

## Data policy (non-negotiable)

| Rule | Enforcement |
|------|-------------|
| Execution prices | Kite LTP / WebSocket TICK only |
| Screening OHLC | Kite `historical()` only — `DataUnavailableError` if missing |
| No fallback LTP | Removed `ltp=100`; missing price → skip trade + log error |
| No stub APIs | Flask `app.py` deprecated; FastAPI `dashboard.py` uses SQLite only |
| No 09:20 cron | `scheduler.py` / `trade_executor.py` exit with error |
| GIFT signal | `yfinance` proxy tagged `SIGNAL_ONLY` — never used for order price |
| Tests only | `tests/mock_feed.py` — never imported in production paths |

## Run

```bash
cd "/Users/iamabymini/Coding Projects/Stock Market/zerodha-momo-rl"
set -a && source .env && set +a

# One-time bootstrap (DB, instruments, paper cash, Kite token check)
python3.11 scripts/setup_local.py

# Engine + dashboard :8080 (supervisor auto-arms; paper mode stays on)
bash src/ops/start_system.sh
```

**Continuous auto-trade loop** (no manual intervention):

- **Enter:** momentum / VWAP / opening-range signals on live ticks
- **Size:** deploys cash across open slots (`MAX_POSITIONS=8`, per-trade cap)
- **Exit:** take-profit 2%, trailing stop 1.5%, stop-loss 4%, MIS square-off at close
- **Learn:** RL records every decision; retrains after each sell (`RL_TRAIN_ON_TRADE=true`)

**Kite login** (evening / token expired):

```bash
python3.11 -m src.auth.kite_auth --auto
# or paste request_token URL while dashboard is up — /kite/callback on :8080
```

Dashboard: http://127.0.0.1:8080/dashboard (public read-only) · Owner: http://127.0.0.1:8080/admin

Set `DASHBOARD_ADMIN_USER` + `DASHBOARD_ADMIN_PASSWORD` in `.env` — public sees everything; only owner can halt, approve budget, or paper-buy.

## GCP + GCS + auto-start (production — **no Mac dependency**)

**One command** (from any machine with `gcloud auth login`):

```bash
cd "/Users/iamabymini/Coding Projects/Stock Market/zerodha-momo-rl"
bash scripts/gcp_deploy.sh
```

VM runs **24×7** (`ENGINE_24X7=true`): supervisor + engine + dashboard via systemd.
Mac can be off — agent learns and trades paper on real NSE data in the cloud.

This provisions (idempotent):
- GCE VM `bharatquant-engine` + **static IP** (asia-south1-a)
- GCS bucket `your-gcp-project-id-bharatquant`
- Firewall :8080 + :22
- Pushes code + `.env` secrets + Kite token to VM
- Runs `vm_bootstrap.sh` → systemd supervisor

Project: `your-gcp-project-id` (shared billing with GeM stack)

Manual steps (split):

```bash
bash scripts/gcp_provision.sh          # VM + IP + bucket only
bash scripts/gcp_sync_secrets.sh       # push /etc/bharatquant/env
bash scripts/vm_bootstrap.sh         # on VM via SSH
```

**Kite developer console** (required for live API orders Apr 2026+):
- Whitelist static IP from `.gcp_state.env` → `GCP_STATIC_IP`
- Redirect URL: `http://<STATIC_IP>:8080/kite/callback`

On VM after deploy:

```bash
gcloud compute ssh bharatquant-engine --zone=asia-south1-a --project=your-gcp-project-id
sudo journalctl -u bharatquant-supervisor -f
curl -s http://127.0.0.1:8080/health
```

Redeploy after code changes:

```bash
bash scripts/gcp_deploy.sh
# or on VM: bash scripts/deploy_vm.sh
```

## RL / PPO

Observer records transitions on every agent decision. Trains after each closed trade and at `SESSION_CLOSE`:

```bash
python3.11 -m src.rl.rl_trainer --version ppo_v1 --epochs 4 --sync-gcs
```

Models: `models/rl/ppo_v1/policy.npz` → synced to `gs://{bucket}/models/ppo_v1/`

## Universe

Full NSE main board (~2,335 symbols): `bash scripts/build_universe.sh`

## Auth (evening)

```bash
python3.11 -m src.auth.kite_totp      # headless TOTP
# or
python3.11 -m src.auth.kite_auth --auto
```

See `docs/EVOLUTION_LOG.md` and `docs/SYSTEM_TRACKER.md` for architecture and milestone tracking.

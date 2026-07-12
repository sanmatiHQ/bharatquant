# BharatQuant — autonomous NSE trading (event-driven)

**No manual data. No fake OHLC. No cron trading.**

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

# Engine + dashboard :8080
bash src/ops/start_system.sh
```

**Kite login** (evening / token expired):

```bash
python3.11 -m src.auth.kite_auth --auto
# or paste request_token URL while dashboard is up — /kite/callback on :8080
```

Dashboard: http://127.0.0.1:8080 · Health: http://127.0.0.1:8080/health

## GCP + GCS + auto-start (production)

```bash
GCP_PROJECT=your-project bash scripts/gcp_provision.sh
# → static IP + gs://{project}-bharatquant bucket
# Whitelist STATIC_IP at developers.kite.trade
```

On VM, enable **market supervisor** (arms engine on GIFT/NSE — not trading cron):

```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl enable --now bharatquant-supervisor
sudo systemctl enable bharatquant-rl-train.timer
```

Set in `/etc/bharatquant/env`: `GCS_BACKUP_BUCKET`, `GCP_STATIC_IP`, `SUPERVISOR_USE_SYSTEMD=true`

**Local Mac** (supervisor instead of manual start):

```bash
python3.11 -m src.ops.market_supervisor
```

## RL / PPO

Observer records transitions on every agent decision. Trains after `SESSION_CLOSE` or nightly:

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

See `docs/EVOLUTION_LOG.md` in parent `Stock Market/docs/` for architecture.

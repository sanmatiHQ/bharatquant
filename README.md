# BharatQuant — autonomous NSE paper/live trading (open source)

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/sanmatiHQ/bharatquant/actions/workflows/ci.yml/badge.svg)](https://github.com/sanmatiHQ/bharatquant/actions/workflows/ci.yml)

**Event-driven NSE agent** — Kite Connect execution, paper→live gate, RL guardrails, telemetry dashboard.

> **Not financial advice.** Research and education only. Trading involves risk of loss. You are responsible for SEBI, exchange, and broker compliance. **Run paper mode first.**

---

## Open source

| Resource | Link |
|----------|------|
| Repository | https://github.com/sanmatiHQ/bharatquant |
| License | [Apache 2.0](LICENSE) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Security | [SECURITY.md](SECURITY.md) |
| Changelog | [CHANGELOG.md](CHANGELOG.md) |
| Architecture tracker | [docs/SYSTEM_TRACKER.md](docs/SYSTEM_TRACKER.md) |
| Design log | [docs/EVOLUTION_LOG.md](docs/EVOLUTION_LOG.md) |

### Community workflow

1. Fork → branch → implement
2. `bash scripts/audit_secrets.sh` + `python3.11 -m pytest tests/ -q`
3. Open PR using the template — describe problem, verification, data-policy compliance

### What is **never** in git

| Artifact | Where it lives |
|----------|----------------|
| Kite API key/secret, password, TOTP | Your `.env` only |
| Access tokens | `.kite_token.json` (gitignored) |
| Trade DB / PnL | `data/trading.db` or VM `/var/lib/bharatquant/` |
| RL weights | `models/rl/` (gitignored) |
| GCP deploy state | `.gcp_state.env` (gitignored) |
| Live TLS host | `deploy/Caddyfile` (generated on VM; see `deploy/Caddyfile.example`) |

**Operators:** if this repo was ever private on your machine, rotate Kite API secret and dashboard password after going public.

---

## Architecture (high level)

```
Kite WebSocket TICK ──► EventBus ──► Strategies ──► ExecutionEngine
                              │              │
                              ▼              ▼
                         Bar aggregator   Risk / Budget / VIX gates
                              │
                              ▼
                    SQLite (trades, positions, RL transitions)
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
   RL guardrails      Dashboard (SSE)        GCS backup (optional)
   shadow backtest    telemetry + XAI
```

**Phases:** `paper_learn` (default) → profitability gate → `TRADING_MODE=live` with hard daily caps.

---

## Quick start (local)

```bash
git clone https://github.com/sanmatiHQ/bharatquant.git
cd bharatquant
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill KITE_API_KEY, KITE_API_SECRET, dashboard password
set -a && source .env && set +a

python3.11 scripts/setup_local.py
bash src/ops/start_system.sh
```

- Dashboard: http://127.0.0.1:8080/dashboard (public read-only)
- Owner actions: http://127.0.0.1:8080/admin

**Kite token refresh:**

```bash
python3.11 -m src.auth.kite_auth --auto
```

---

## GCP deploy (optional)

```bash
# Fill .env: GCP_PROJECT_ID, Kite creds, DASHBOARD_ADMIN_PASSWORD, BHARATQUANT_PUBLIC_HOST
bash scripts/gcp_deploy.sh
```

| Step | What it does |
|------|----------------|
| `gcp_provision.sh` | VM + static IP + GCS bucket |
| `gcp_sync_secrets.sh` | Push `.env` secrets to VM only |
| `vm_bootstrap.sh` | systemd supervisor + deps |

**Kite developer console:** whitelist VM static IP; redirect `https://YOUR_HOST/kite/callback`

Non-secret production defaults: `deploy/bharatquant.env.production` (placeholders only).

---

## Daily budget & data policy

| Rule | Detail |
|------|--------|
| Deploy cap | ₹1,500–₹2,000/day (`DAILY_INVESTMENT_MIN/MAX`) after live gate |
| Paper phase | Real Kite ticks, paper orders, RL on live market |
| Execution prices | Kite LTP / WebSocket only — no synthetic OHLC |
| Screening | Kite `historical()` or `DataUnavailableError` |
| GIFT / macro | Signal tags only — never order price |

---

## RL / guardrails

- Observer records every decision transition
- **Guarded promote:** low LR → 30d shadow backtest → revert on regression
- Post-market train at 16:15 IST (`POSTMARKET_RL_DEFER=true`)

```bash
python3.11 -m src.rl.rl_trainer --version ppo_v1 --epochs 4
```

---

## Quality gates

```bash
bash scripts/audit_secrets.sh     # secrets + infra fingerprint scan
python3.11 -m pytest tests/ -q    # full test suite
```

CI runs both on every push/PR to `main`.

### One-time git history scrub (maintainers)

If old commits contain your GCP project ID or VM IP:

```bash
bash scripts/scrub_git_history.sh
git push origin main --force-with-lease
```

---

## Reporting security issues

Use [GitHub Security Advisories](https://github.com/sanmatiHQ/bharatquant/security/advisories/new) — **not** public issues. See [SECURITY.md](SECURITY.md).

---

*Built for autonomous NSE research. Use at your own risk.*

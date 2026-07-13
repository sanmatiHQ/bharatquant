# BharatQuant — autonomous NSE paper/live trading (open source)

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)

**Event-driven NSE agent** — Kite Connect execution, paper→live gate, RL guardrails, telemetry dashboard.

> **Not financial advice.** This software is for research and education. Trading involves risk of loss. You are responsible for compliance with SEBI, exchange, and broker rules. Run paper mode first.

## Open source

- **License:** [Apache 2.0](LICENSE)
- **Issues & PRs:** [github.com/sanmatiHQ/bharatquant](https://github.com/sanmatiHQ/bharatquant)
- **Contributing:** fork → branch → tests green → PR with a short problem/solution note
- **Security:** never commit `.env`, Kite tokens, or DB files — run `bash scripts/audit_secrets.sh` before pushing

### What is **not** in this repo (by design)

| Never committed | Where it lives |
|-----------------|----------------|
| Kite API key/secret, password, TOTP | Your `.env` (copy from `.env.example`) |
| Access tokens | `.kite_token.json` (local / VM only) |
| SQLite trades & PnL | `data/trading.db` or VM `/var/lib/bharatquant/` |
| RL model weights | `models/rl/` (optional GCS sync) |
| GCP deploy state | `.gcp_state.env` |
| Generated TLS config | `deploy/Caddyfile` (use `deploy/Caddyfile.example`) |

If this repo was ever private with real secrets in local-only files, **rotate Kite and dashboard passwords** before going public.

---

## Daily budget (hard cap)

| Rule | Detail |
|------|--------|
| Deploy cap | **₹1,500–₹2,000/day** via `DAILY_INVESTMENT_MIN/MAX` (live Zerodha after profitability) |
| Phase 1 | **paper_learn** — real Kite ticks, paper orders, RL on live market |
| Phase 2 | **live_deploy** — set `TRADING_MODE=live` after `LIVE_GATE_MIN_PAPER_RETURN_PCT` met |
| No auto top-up | Paper cash seeds **once** — agent cannot invent money |
| Raise limit | Agent requests via dashboard → you **Approve** within **15 min** or request expires |

## Data policy (non-negotiable)

| Rule | Enforcement |
|------|-------------|
| Execution prices | Kite LTP / WebSocket TICK only |
| Screening OHLC | Kite `historical()` only — `DataUnavailableError` if missing |
| No fallback LTP | Missing price → skip trade + log error |
| GIFT signal | `yfinance` proxy tagged `SIGNAL_ONLY` — never used for order price |
| Tests only | `tests/mock_feed.py` — never imported in production paths |

## Quick start (local)

```bash
git clone https://github.com/sanmatiHQ/bharatquant.git
cd bharatquant
cp .env.example .env   # fill KITE_API_KEY, KITE_API_SECRET, etc.
set -a && source .env && set +a

python3.11 scripts/setup_local.py
bash src/ops/start_system.sh
```

Dashboard: http://127.0.0.1:8080/dashboard

**Kite login** (token expired):

```bash
python3.11 -m src.auth.kite_auth --auto
```

## GCP deploy (optional)

```bash
# Set GCP_PROJECT_ID, Kite creds, dashboard password in .env first
bash scripts/gcp_deploy.sh
```

- Provisions GCE VM + static IP + GCS bucket (idempotent)
- Secrets pushed from **your** `.env` only — never from git
- Kite console: whitelist VM static IP; redirect `https://YOUR_HOST/kite/callback`

See `deploy/bharatquant.env.production` for non-secret production defaults (placeholders only).

## Architecture docs

- `docs/EVOLUTION_LOG.md` — design decisions & ops notes (sanitized)
- `docs/SYSTEM_TRACKER.md` — milestone tracker
- `CHANGELOG.md` — release history

## RL / PPO

Observer records transitions on every agent decision. Guarded training with shadow backtest before weight promotion:

```bash
python3.11 -m src.rl.rl_trainer --version ppo_v1 --epochs 4
```

## Tests

```bash
python3.11 -m pytest tests/ -q
bash scripts/audit_secrets.sh
```

## Reporting security issues

Open a **private** GitHub security advisory on the repo, or email the maintainer listed on the GitHub org. Do **not** post API keys or account IDs in public issues.

---

*Built for autonomous NSE research. Use at your own risk.*

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
set -a && source .env && set +a
bash src/ops/start_system.sh          # engine + dashboard :8080
# or separately:
python3.11 -m src.engine.main
python3.11 -m src.api.dashboard
```

## Universe

Full NSE main board (~2,335 symbols): `bash scripts/build_universe.sh`

## Auth (evening)

```bash
python3.11 -m src.auth.kite_totp      # headless TOTP
# or
python3.11 -m src.auth.kite_auth --auto
```

See `docs/EVOLUTION_LOG.md` in parent `Stock Market/docs/` for architecture.

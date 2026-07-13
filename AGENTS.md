# BharatQuant — Agent Operating Contract

Autonomous NSE paper/live trading agent. Python 3.11. SQLite on VM. Zerodha Kite.

## Services

| Component | Port | Entry |
|-----------|------|-------|
| Engine + Dashboard | 5050/443 | `python3.11 -m src.engine.main` |
| Dashboard API | same | `src/api/dashboard.py` |

## Architecture (do not break)

```
Pollers → EventBus → ContextUpdater → Strategies → SignalCombiner → AgentRouter.fuse → ExecutionEngine
                ↓                              ↓
         strategy_learning              bandit + RL observer
```

## Edit boundaries (AI agents)

| Area | Rule |
|------|------|
| `src/strategies/` | **Primary zone** — add/extend strategies here |
| `src/ingest/` | Add pollers only; reuse `nse_session.py` handshake |
| `src/intelligence/` | Learning loops, corporate intel, discovery |
| `src/agent/signal_combiner.py` | Net exposure arbitration — extend, don't bypass |
| `src/agent/router.py` | Fuse logic only — no direct broker calls |
| `src/engine/execution_engine.py` | Execution + ledger — minimal diffs |
| `src/ops/reconciliation.py` | Broker sync + halt gates |
| `common/` | **Does not exist** — use `src/` modules |
| `data/trading.db` | Never commit; Atlas not used (local SQLite on VM) |

**Forbidden:** bypassing `SignalCombiner` for multi-strategy ticks; strategies calling NSE/BSE HTTP directly; writing peer Mongo; Redis (single VM).

## Learning invariant

Every signal must be learnable:

1. `strategy_ledger` records all candidates
2. `strategy_signal_outcomes` labels forward returns
3. `strategy_learn_weights` + bandit adjust weights
4. `rl_transitions` seeds from outcomes
5. `strategy_discovery` promotes winning rules → `learned_*` strategies

**US → NSE localization:** QuantifiedStrategies / 151TS patterns with US session timing are implemented as IST-localized variants (`nse_localized.py`). Paper-learn via outcomes — never hard-exclude a literature strategy without Indian market evidence.

**Market awareness:** `market_session.py` + `market/market_awareness.py` own IST phase, open/close, expiry. `sentiment_index.py` computes fear/greed (0–100). `news_context.py` digests NSE/BSE filings. All NSE activity types label into `corporate_event_outcomes` for learning.

## Mandatory checks before merge

```bash
bash scripts/audit_secrets.sh
python3.11 -m pytest tests/ -q
```

Pre-commit hooks run the same (install: `pip install pre-commit && pre-commit install`).

## Deploy

```bash
bash scripts/gcp_deploy.sh
bash scripts/verify_deploy.sh
```

## Env (VM: `/etc/bharatquant/env`)

- `TRADING_MODE=paper|live`
- `RECONCILE_INTERVAL_SEC=60` (live) / `300` (paper)
- `RECONCILE_HALT_AFTER=3`
- `SIGNAL_COMBINE_WINDOW_MS=500`
- `SIGNAL_NET_THRESHOLD=0.18`

## Key docs

- `docs/EVOLUTION_LOG.md` — read last 10 entries before tasks
- `docs/SYSTEM_TRACKER.md` — tracker rows
- `CHANGELOG.md` — release notes

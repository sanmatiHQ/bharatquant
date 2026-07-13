# Contributing to BharatQuant

Thank you for helping improve autonomous NSE research tooling. This project is **Apache 2.0** — see [LICENSE](LICENSE).

## Before you start

1. Read [README.md](README.md) — data policy and security rules are non-negotiable.
2. Run paper mode locally before proposing execution-path changes.
3. Never commit secrets — copy `.env.example` → `.env` locally only.

## Development setup

```bash
git clone https://github.com/sanmatiHQ/bharatquant.git
cd bharatquant
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill Kite test credentials
python3.11 scripts/setup_local.py
```

## Quality gates (required for merge)

```bash
bash scripts/audit_secrets.sh          # must exit 0
python3.11 -m pytest tests/ -q         # all green
```

CI runs the same checks on every PR.

## Pull request process

1. **Fork** → feature branch from `main` (`feat/…`, `fix/…`, `docs/…`).
2. **One concern per PR** — easier review, faster merge.
3. **Tests** — add or update tests for behavior changes; bugfixes need a regression test when practical.
4. **Docs** — update `CHANGELOG.md` for user-visible changes; `docs/EVOLUTION_LOG.md` for design/ops notes.
5. **Description** — problem, approach, how you verified (commands + outcome).

## Code guidelines

| Area | Rule |
|------|------|
| Execution prices | Kite LTP / WebSocket only — no synthetic OHLC in production paths |
| Secrets | Env vars only; use `__PLACEHOLDER__` in templates |
| Collections / DB | SQLite schema changes need `src/db/migrations.sql` |
| Agent boundaries | Keep `src/` modular — engine, ops, rl, api separated |
| LLM | Macro bias / post-mortem only — **never** on order placement path |

## What we welcome

- Bug fixes with reproduction steps
- Performance improvements (feed latency, screening, RL guardrails)
- Documentation and onboarding clarity
- Test coverage for edge cases
- Security hardening (with responsible disclosure for vulnerabilities)

## What we will reject

- Committed `.env`, tokens, or SQLite databases
- Hardcoded API keys or production hostnames
- Fallback fake prices for execution
- Changes that disable paper→live gate without justification

## Security vulnerabilities

**Do not** open public issues for credential leaks or exploits. Use [GitHub Security Advisories](https://github.com/sanmatiHQ/bharatquant/security/advisories/new) or see [SECURITY.md](SECURITY.md).

## License

By contributing, you agree your contributions are licensed under Apache 2.0.

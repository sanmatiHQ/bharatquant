# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| `main` branch | Yes |
| Older tags | Best effort |

## Reporting a vulnerability

**Please do not** post API keys, Kite tokens, dashboard passwords, or exploit details in public GitHub issues.

1. Open a **private** [GitHub Security Advisory](https://github.com/sanmatiHQ/bharatquant/security/advisories/new), or
2. Contact the maintainers via the GitHub organization profile.

Include:
- Description and impact
- Steps to reproduce
- Suggested fix (if any)

We aim to acknowledge within **72 hours** and patch critical issues on `main` promptly.

## Secrets hygiene (operators)

| Never commit | Store instead |
|--------------|---------------|
| `KITE_API_KEY`, `KITE_API_SECRET` | `.env` / GCP Secret Manager |
| `KITE_PASSWORD`, `KITE_TOTP_SECRET` | `.env` / Secret Manager |
| `.kite_token.json` | Local disk or `/var/lib/bharatquant/` on VM |
| `DASHBOARD_ADMIN_PASSWORD` | `.env` only |
| SQLite with trades/PnL | `data/` or VM `/var/lib/bharatquant/` |

Before every push:

```bash
bash scripts/audit_secrets.sh
```

## If you accidentally committed a secret

1. **Rotate immediately** — Kite API secret, dashboard password, any exposed API key.
2. Remove from git history: `bash scripts/scrub_git_history.sh` (infra) or [GitHub secret removal guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
3. Force-push only after rotation.

## Scope

In scope:
- Authentication bypass on dashboard owner actions
- Remote code execution via unsanitized inputs
- Leakage of credentials in logs or API responses
- Trading safety bypass (halt, budget gate, live gate)

Out of scope:
- Social engineering
- Denial of service against your own VM
- Losses from live trading after you enable `TRADING_MODE=live`

## Safe harbor

We support good-faith security research on **your own fork** with paper mode. Do not test against production VMs you do not own.

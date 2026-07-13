## Summary

<!-- What changed and why (1–3 sentences) -->

## Type

- [ ] Bug fix
- [ ] Feature
- [ ] Docs / OSS hygiene
- [ ] Refactor (no behavior change)

## Verification

```bash
bash scripts/audit_secrets.sh
python3.11 -m pytest tests/ -q
```

<!-- Paste command output or describe manual test -->

## Checklist

- [ ] No `.env`, tokens, DB files, or production hostnames in diff
- [ ] `CHANGELOG.md` updated if user-visible
- [ ] Tests added/updated for behavior changes
- [ ] Paper mode verified for execution-path changes

## Data policy

- [ ] Execution prices still Kite-only (no synthetic LTP in production paths)

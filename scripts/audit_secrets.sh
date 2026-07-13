#!/usr/bin/env bash
# BharatQuant open-source hygiene gate — run before every push and in CI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAIL=0
WARN=0

echo "==> BharatQuant open-source audit"

# Required OSS files
for required in LICENSE README.md .env.example .gitignore; do
  if [[ ! -f "$required" ]]; then
    echo "FAIL: missing required file: $required"
    FAIL=1
  fi
done

# Must never be tracked
FORBIDDEN=(
  .env
  .kite_token.json
  .gcp_state.env
  data/trading.db
  data/bharatquant.db
  deploy/Caddyfile
)
for forbidden in "${FORBIDDEN[@]}"; do
  if git ls-files --error-unmatch "$forbidden" &>/dev/null; then
    echo "FAIL: tracked forbidden file: $forbidden"
    FAIL=1
  fi
done

# Infrastructure fingerprints (use placeholders in git)
SKIP_FILES=(
  scripts/gcp_sync_secrets.sh
  scripts/secrets_sync.sh
  scripts/audit_secrets.sh
  scripts/scrub_git_history.sh
  tests/test_open_source_hygiene.py
)
INFRA_PATTERNS=(
  '34\.93\.102'
  '34-93-102'
  'your-gcp-project-id'
  'iamabymini'
  'CI1482'
)
while IFS= read -r -d '' f; do
  skip=0
  for s in "${SKIP_FILES[@]}"; do
    [[ "$f" == "$s" ]] && skip=1 && break
  done
  [[ "$skip" -eq 1 ]] && continue
  for pat in "${INFRA_PATTERNS[@]}"; do
    if rg -q "$pat" "$f" 2>/dev/null; then
      echo "FAIL: infra pattern '$pat' in tracked file $f"
      FAIL=1
    fi
  done
done < <(git ls-files -z)

# Credential patterns (placeholders __KEY__ OK)
SECRET_PATTERNS=(
  'KITE_API_SECRET=[^_<]'
  'KITE_PASSWORD=[^_<]'
  'KITE_TOTP_SECRET=[^_<]'
  'GEMINI_API_KEY=[^_<]'
  'OPENAI_API_KEY=[^_<]'
  'ANTHROPIC_API_KEY=[^_<]'
  'DASHBOARD_ADMIN_PASSWORD=[^_<c]'
  'TELEGRAM_BOT_TOKEN=[0-9]'
  'sk-[a-zA-Z0-9]{20,}'
  'mongodb\+srv://'
)
while IFS= read -r -d '' f; do
  skip=0
  for s in "${SKIP_FILES[@]}"; do
    [[ "$f" == "$s" ]] && skip=1 && break
  done
  [[ "$skip" -eq 1 ]] && continue
  for pat in "${SECRET_PATTERNS[@]}"; do
    if rg -q "$pat" "$f" 2>/dev/null; then
      echo "FAIL: secret pattern '$pat' in $f"
      FAIL=1
    fi
  done
done < <(git ls-files -z)

# Git history — must be scrubbed before public release
HISTORY_HITS=$(git log -p --all 2>/dev/null | rg -c '34\.93\.102|34-93-102|your-gcp-project-id' || true)
if [[ "${HISTORY_HITS:-0}" -gt 0 ]]; then
  echo "FAIL: git history contains $HISTORY_HITS infra fingerprint lines — run: bash scripts/scrub_git_history.sh"
  FAIL=1
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "OK: tracked tree clean (warnings: $WARN)"
  exit 0
fi
echo "Fix FAIL items above before publishing."
exit 1

#!/usr/bin/env bash
# BharatQuant open-source hygiene gate — run before every push and in CI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAIL=0

echo "==> BharatQuant open-source audit"

# Required OSS files
for required in LICENSE README.md CONTRIBUTING.md SECURITY.md .env.example .gitignore; do
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

SKIP_FILES=(
  scripts/gcp_sync_secrets.sh
  scripts/secrets_sync.sh
  scripts/audit_secrets.sh
  scripts/scrub_git_history.sh
  scripts/verify_deploy.sh
  tests/test_open_source_hygiene.py
)

# Production infra only — placeholders like your-gcp-project-id are OK
INFRA_PATTERNS=(
  '34\.93\.102'
  '34-93-102-20\.sslip'
  'gem-bid-automation'
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

# Git history — production fingerprints in real content (exclude audit/scrub sources)
_check_history_needle() {
  local needle="$1"
  local hits
  hits=$(git log --all -S "$needle" --oneline -- \
    . ':(exclude)scripts/audit_secrets.sh' \
    ':(exclude)scripts/scrub_git_history.sh' \
    ':(exclude)tests/test_open_source_hygiene.py' 2>/dev/null || true)
  if [[ -n "$hits" ]]; then
    echo "FAIL: git history still contains: $needle"
    echo "$hits" | head -3
    FAIL=1
  fi
}
_check_history_needle '34.93.102.20'
_check_history_needle '34-93-102-20.sslip.io'
_check_history_needle 'gem-bid-automation-a1'

if [[ "$FAIL" -eq 0 ]]; then
  echo "OK: open-source hygiene passed"
  exit 0
fi
echo "Fix FAIL items above before publishing."
exit 1

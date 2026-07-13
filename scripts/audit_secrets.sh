#!/usr/bin/env bash
# Pre-publish / pre-push secret audit — fails on likely leaked credentials in tracked files.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAIL=0

echo "==> BharatQuant secret audit"

# Must never be tracked
for forbidden in .env .kite_token.json .gcp_state.env data/trading.db data/bharatquant.db; do
  if git ls-files --error-unmatch "$forbidden" &>/dev/null; then
    echo "FAIL: tracked forbidden file: $forbidden"
    FAIL=1
  fi
done

# Patterns that should not appear in tracked source (placeholders OK)
PATTERNS=(
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
  case "$f" in
    scripts/gcp_sync_secrets.sh|scripts/secrets_sync.sh) continue ;;
  esac
  for pat in "${PATTERNS[@]}"; do
    if rg -q "$pat" "$f" 2>/dev/null; then
      echo "FAIL: pattern '$pat' in $f"
      FAIL=1
    fi
  done
done < <(git ls-files -z)

if [[ "$FAIL" -eq 0 ]]; then
  echo "OK: no obvious secrets in tracked files"
  exit 0
fi
echo "Fix issues above before publishing or pushing."
exit 1

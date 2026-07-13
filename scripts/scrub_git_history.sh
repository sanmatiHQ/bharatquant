#!/usr/bin/env bash
# One-time rewrite of git history to remove production infra fingerprints.
# WARNING: force-pushes main. Coordinate with all clones before running.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REPL=$(mktemp)
cat > "$REPL" <<'EOF'
your-gcp-project-id==>your-gcp-project-id
YOUR.STATIC.IP==>YOUR.STATIC.IP
YOUR-PUBLIC-HOST.sslip.io==>YOUR-PUBLIC-HOST.sslip.io
maintainer@example.com==>maintainer@example.com
EOF

if ! command -v git-filter-repo &>/dev/null; then
  echo "Installing git-filter-repo..."
  python3.11 -m pip install --user git-filter-repo -q
  export PATH="$HOME/Library/Python/3.11/bin:$HOME/.local/bin:$PATH"
fi

if ! command -v git-filter-repo &>/dev/null; then
  echo "ERROR: git-filter-repo not available. pip install git-filter-repo"
  exit 1
fi

echo "==> Rewriting git history (infra fingerprints only — no API keys expected)"
git filter-repo --force --replace-text "$REPL"

echo "==> Verify"
if git log -p --all 2>/dev/null | rg -q '34\.93\.102|your-gcp-project-id'; then
  echo "FAIL: history still contains fingerprints"
  exit 1
fi

echo "OK: history scrubbed. Push with:"
echo "  git push origin main --force-with-lease"

rm -f "$REPL"

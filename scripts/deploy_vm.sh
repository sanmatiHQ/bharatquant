#!/usr/bin/env bash
# Deploy BharatQuant on existing GCE VM — git pull + restart services (BQ-18)
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/zerodha-momo-rl}"
BRANCH="${BRANCH:-main}"

cd "$REPO_DIR"
echo "==> Pull $BRANCH"
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"

echo "==> Install deps"
python3.11 -m pip install -q -r requirements.txt

echo "==> Run tests"
python3.11 -m pytest tests/ -q

echo "==> Restart systemd units"
sudo systemctl daemon-reload
sudo systemctl restart bharatquant-engine bharatquant-dashboard
sudo systemctl status bharatquant-engine --no-pager
sudo systemctl status bharatquant-dashboard --no-pager

echo "==> Health"
curl -sf "http://127.0.0.1:${PORT:-8080}/health" | python3.11 -m json.tool

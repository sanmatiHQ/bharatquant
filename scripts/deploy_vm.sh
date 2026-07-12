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
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/ 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl enable bharatquant-supervisor bharatquant-rl-train.timer 2>/dev/null || true
sudo systemctl restart bharatquant-supervisor
sudo systemctl restart bharatquant-engine bharatquant-dashboard 2>/dev/null || true
sudo systemctl status bharatquant-supervisor --no-pager

echo "==> Health"
curl -sf "http://127.0.0.1:${PORT:-8080}/health" | python3.11 -m json.tool

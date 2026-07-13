#!/usr/bin/env bash
# Full GCP deploy: provision (if needed) → rsync code → sync secrets → VM bootstrap
#
# Prereq: gcloud auth login
# Usage:   bash scripts/gcp_deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STATE_FILE="$ROOT/.gcp_state.env"
PROJECT="${GCP_PROJECT_ID:-your-gcp-project-id}"
ZONE="${GCP_ZONE:-asia-south1-a}"
VM_NAME="${VM_NAME:-bharatquant-engine}"
REMOTE_DIR="/opt/bharatquant/zerodha-momo-rl"

if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1 | grep -q .; then
  echo "ERROR: Run: gcloud auth login"
  exit 1
fi

SSH_OPTS=(--tunnel-through-iap)
if ! gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" "${SSH_OPTS[@]}" --command "echo ok" &>/dev/null 2>&1; then
  echo "WARN: IAP SSH unavailable — using direct SSH"
  SSH_OPTS=()
fi

_ssh() {
  gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" "${SSH_OPTS[@]}" "$@"
}

echo "==> [1/5] Provision VM + static IP + GCS (idempotent)"
bash "$ROOT/scripts/gcp_auth_check.sh"
bash "$ROOT/scripts/gcp_provision.sh"

# shellcheck disable=SC1090
source "$STATE_FILE"

echo "==> [2/5] Wait for VM SSH"
for i in $(seq 1 30); do
  if _ssh --command "echo ok" &>/dev/null; then
    break
  fi
  echo "  waiting... ($i/30)"
  sleep 10
done

echo "==> [3/5] Rsync repo to VM (excludes secrets + db)"
_ssh --command "sudo mkdir -p /opt/bharatquant && sudo chown \$(whoami):\$(whoami) /opt/bharatquant"

tar czf - -C "$ROOT" \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.kite_token.json' \
  --exclude='.kite_token.json.*' \
  --exclude='data/trading.db' \
  --exclude='data/trading.db-*' \
  --exclude='backups' \
  --exclude='logs' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='venv' \
  --exclude='.venv' \
  --exclude='.gcp_state.env' \
  . | \
  _ssh --command "sudo mkdir -p '$REMOTE_DIR' && sudo tar xzf - -C '$REMOTE_DIR' --overwrite && sudo chown -R bharatquant:bharatquant '$REMOTE_DIR'"

echo "==> [4/5] Sync secrets"
export GCP_USE_IAP_SSH="${#SSH_OPTS[@]}"
bash "$ROOT/scripts/gcp_sync_secrets.sh"

echo "==> [5/5] VM bootstrap + start supervisor"
_ssh --command "sudo bash '$REMOTE_DIR/scripts/vm_bootstrap.sh'"

echo "==> [6/6] Post-deploy: RL regimes + sandbox refresh"
_ssh --command "sudo -u bharatquant bash -lc 'set -a && source /etc/bharatquant/env && set +a && cd \"$REMOTE_DIR\" && python3.11 -m src.rl.rl_trainer --train-regimes --restore-gcs 2>/dev/null || true && python3.11 -m src.rl.rl_trainer --force-postmarket 2>/dev/null || true'"

STATIC_IP="${GCP_STATIC_IP:-}"
echo ""
echo "=== DEPLOYED ==="
echo "Dashboard:  http://${STATIC_IP}:8080/dashboard"
echo "Health:     http://${STATIC_IP}:8080/health"
echo "Kite IP whitelist: ${STATIC_IP}"
echo "Kite redirect:     http://${STATIC_IP}:8080/kite/callback"
echo "SSH: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT --tunnel-through-iap"
echo "Logs: gcloud compute ssh $VM_NAME --zone=$ZONE --tunnel-through-iap --command 'sudo journalctl -u bharatquant-supervisor -f'"

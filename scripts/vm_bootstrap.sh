#!/usr/bin/env bash
# BharatQuant VM bootstrap — run ON the GCE instance (root or sudo).
# Installs deps, systemd units, dirs. Repo must already exist at REPO_DIR.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/bharatquant/zerodha-momo-rl}"
ENV_FILE="${ENV_FILE:-/etc/bharatquant/env}"
BQ_USER="${BQ_USER:-bharatquant}"

echo "==> VM bootstrap BharatQuant at $REPO_DIR"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3.11 python3.11-venv python3.11-dev python3-pip \
  git curl build-essential sqlite3

id "$BQ_USER" &>/dev/null || useradd -r -m -d /home/"$BQ_USER" -s /bin/bash "$BQ_USER"

mkdir -p /opt/bharatquant /var/lib/bharatquant /var/log/bharatquant /etc/bharatquant
chown -R "$BQ_USER:$BQ_USER" /opt/bharatquant /var/lib/bharatquant /var/log/bharatquant

if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "ERROR: repo not found at $REPO_DIR — deploy must scp/rsync code first"
  exit 1
fi

chown -R "$BQ_USER:$BQ_USER" "$REPO_DIR"

echo "==> Python deps"
sudo -u "$BQ_USER" bash -lc "cd '$REPO_DIR' && python3.11 -m pip install --user -q -r requirements.txt"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "==> Seed env from template (secrets filled by gcp_sync_secrets.sh)"
  cp "$REPO_DIR/deploy/bharatquant.env.production" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

# Inject metadata when available (GCP)
META_IP=$(curl -sf -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip 2>/dev/null || true)
if [[ -n "$META_IP" ]]; then
  sed -i "s|__GCP_STATIC_IP__|$META_IP|g" "$ENV_FILE"
  sed -i "s|http://__GCP_STATIC_IP__:8080|http://$META_IP:8080|g" "$ENV_FILE"
fi

PROJECT=$(curl -sf -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/project/project-id 2>/dev/null || true)
if [[ -n "$PROJECT" ]]; then
  sed -i "s|__GCP_PROJECT_ID__|$PROJECT|g" "$ENV_FILE"
  sed -i "s|__GCS_BACKUP_BUCKET__|${PROJECT}-bharatquant|g" "$ENV_FILE"
fi

echo "==> systemd units"
cp "$REPO_DIR"/deploy/*.service "$REPO_DIR"/deploy/*.timer /etc/systemd/system/ 2>/dev/null || true
systemctl daemon-reload
systemctl enable bharatquant-supervisor bharatquant-rl-train.timer

echo "==> App setup (DB, instruments, paper cash)"
sudo -u "$BQ_USER" bash -lc "set -a && source '$ENV_FILE' && set +a && cd '$REPO_DIR' && python3.11 scripts/setup_local.py" || true

systemctl restart bharatquant-supervisor || systemctl start bharatquant-supervisor
sleep 3
systemctl is-active bharatquant-supervisor && echo "supervisor: active" || echo "supervisor: check logs"

echo "==> Bootstrap done"
echo "Dashboard: http://${META_IP:-127.0.0.1}:8080/dashboard"
echo "Kite redirect: http://${META_IP:-__IP__}:8080/kite/callback"

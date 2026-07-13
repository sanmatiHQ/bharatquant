#!/usr/bin/env bash
# Install Caddy + TLS on BharatQuant VM. Run ON the VM (sudo).
# Uses YOUR-PUBLIC-HOST.sslip.io → static IP (no custom DNS required).
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/bharatquant/zerodha-momo-rl}"
ENV_FILE="${ENV_FILE:-/etc/bharatquant/env}"
HOST="${BHARATQUANT_PUBLIC_HOST:-YOUR-PUBLIC-HOST.sslip.io}"

echo "==> Install Caddy"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
if [[ ! -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]]; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
fi
apt-get install -y -qq caddy

echo "==> Caddyfile"
install -m 644 "$REPO_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl enable caddy
systemctl restart caddy

echo "==> Update Kite redirect URL"
REDIRECT="https://${HOST}/kite/callback"
if grep -q '^KITE_REDIRECT_URL=' "$ENV_FILE"; then
  sed -i "s|^KITE_REDIRECT_URL=.*|KITE_REDIRECT_URL=${REDIRECT}|" "$ENV_FILE"
else
  echo "KITE_REDIRECT_URL=${REDIRECT}" >> "$ENV_FILE"
fi
if grep -q '^BHARATQUANT_PUBLIC_HOST=' "$ENV_FILE"; then
  sed -i "s|^BHARATQUANT_PUBLIC_HOST=.*|BHARATQUANT_PUBLIC_HOST=${HOST}|" "$ENV_FILE"
else
  echo "BHARATQUANT_PUBLIC_HOST=${HOST}" >> "$ENV_FILE"
fi

systemctl restart bharatquant-dashboard bharatquant-engine 2>/dev/null || true

echo "==> HTTPS ready"
echo "Dashboard:  https://${HOST}/dashboard"
echo "Kite login: https://${HOST}/login"
echo "Kite redirect (paste in Zerodha console): ${REDIRECT}"
echo "IP whitelist (unchanged): $(grep '^GCP_STATIC_IP=' "$ENV_FILE" | cut -d= -f2-)"

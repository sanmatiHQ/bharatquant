#!/usr/bin/env bash
# Install Caddy + TLS on BharatQuant VM. Run ON the VM (sudo).
# Uses sslip.io hostname from env — no custom DNS required.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/bharatquant/zerodha-momo-rl}"
ENV_FILE="${ENV_FILE:-/etc/bharatquant/env}"
HOST="${BHARATQUANT_PUBLIC_HOST:-}"
if [[ -z "$HOST" ]]; then
  echo "Set BHARATQUANT_PUBLIC_HOST in /etc/bharatquant/env (e.g. 203-0-113-10.sslip.io)"
  exit 1
fi

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
cat > /etc/caddy/Caddyfile <<EOF
${HOST} {
	reverse_proxy 127.0.0.1:8080
}
EOF
chmod 644 /etc/caddy/Caddyfile
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

#!/usr/bin/env bash
# Push local secrets to VM /etc/bharatquant/env (never commit output).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STATE_FILE="$ROOT/.gcp_state.env"
if [[ -f "$STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$STATE_FILE"
fi

PROJECT="${GCP_PROJECT_ID:-your-gcp-project-id}"
ZONE="${GCP_ZONE:-asia-south1-a}"
VM_NAME="${VM_NAME:-bharatquant-engine}"
LOCAL_ENV="${LOCAL_ENV:-$ROOT/.env}"

if [[ ! -f "$LOCAL_ENV" ]]; then
  echo "ERROR: $LOCAL_ENV missing — copy .env.example and fill Kite creds"
  exit 1
fi

# shellcheck disable=SC1090
set -a && source "$LOCAL_ENV" && set +a

STATIC_IP="${GCP_STATIC_IP:-}"
if [[ -z "$STATIC_IP" ]]; then
  STATIC_IP=$(gcloud compute addresses describe "${VM_NAME}-ip" --region="${GCP_REGION:-asia-south1}" \
    --project="$PROJECT" --format='get(address)' 2>/dev/null || true)
fi

BUCKET="${GCS_BACKUP_BUCKET:-${PROJECT}-bharatquant}"
TMP_ENV=$(mktemp)
trap 'rm -f "$TMP_ENV"' EXIT

cp "$ROOT/deploy/bharatquant.env.production" "$TMP_ENV"
sed -i '' "s|__GCP_PROJECT_ID__|${PROJECT}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__GCP_PROJECT_ID__|${PROJECT}|g" "$TMP_ENV"
sed -i '' "s|__GCP_STATIC_IP__|${STATIC_IP}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__GCP_STATIC_IP__|${STATIC_IP}|g" "$TMP_ENV"
sed -i '' "s|__GCS_BACKUP_BUCKET__|${BUCKET}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__GCS_BACKUP_BUCKET__|${BUCKET}|g" "$TMP_ENV"
sed -i '' "s|__KITE_API_KEY__|${KITE_API_KEY}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__KITE_API_KEY__|${KITE_API_KEY}|g" "$TMP_ENV"
sed -i '' "s|__KITE_API_SECRET__|${KITE_API_SECRET}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__KITE_API_SECRET__|${KITE_API_SECRET}|g" "$TMP_ENV"
sed -i '' "s|__KITE_USER_ID__|${KITE_USER_ID:-}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__KITE_USER_ID__|${KITE_USER_ID:-}|g" "$TMP_ENV"
sed -i '' "s|__KITE_PASSWORD__|${KITE_PASSWORD:-}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__KITE_PASSWORD__|${KITE_PASSWORD:-}|g" "$TMP_ENV"
sed -i '' "s|__KITE_TOTP_SECRET__|${KITE_TOTP_SECRET:-}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__KITE_TOTP_SECRET__|${KITE_TOTP_SECRET:-}|g" "$TMP_ENV"

echo "==> Upload /etc/bharatquant/env"
gcloud compute scp "$TMP_ENV" "${VM_NAME}:/tmp/bharatquant.env" --zone="$ZONE" --project="$PROJECT"
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" --command \
  "sudo mkdir -p /etc/bharatquant && sudo mv /tmp/bharatquant.env /etc/bharatquant/env && sudo chmod 600 /etc/bharatquant/env"

TOKEN_FILE="${KITE_ACCESS_TOKEN_FILE:-$ROOT/.kite_token.json}"
if [[ -f "$TOKEN_FILE" ]]; then
  echo "==> Upload Kite token"
  gcloud compute scp "$TOKEN_FILE" "${VM_NAME}:/tmp/.kite_token.json" --zone="$ZONE" --project="$PROJECT"
  gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" --command \
    "sudo mv /tmp/.kite_token.json /var/lib/bharatquant/.kite_token.json && sudo chown bharatquant:bharatquant /var/lib/bharatquant/.kite_token.json && sudo chmod 600 /var/lib/bharatquant/.kite_token.json"
fi

echo "==> Secrets synced to $VM_NAME"

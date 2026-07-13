#!/usr/bin/env bash
# Pull secrets from GCP Secret Manager into /etc/bharatquant/env
# Usage: GCP_PROJECT=bharatquant-prod bash scripts/secrets_sync.sh
set -euo pipefail
PROJECT="${GCP_PROJECT:-your-gcp-project-id}"
OUT="/etc/bharatquant/env"
sudo mkdir -p /etc/bharatquant
sudo touch "$OUT"
sudo chmod 600 "$OUT"

for key in KITE_API_KEY KITE_API_SECRET KITE_USER_ID KITE_PASSWORD KITE_TOTP_SECRET GEMINI_API_KEY TELEGRAM_BOT_TOKEN; do
  val=$(gcloud secrets versions access latest --secret="bq-${key}" --project="$PROJECT" 2>/dev/null || true)
  if [[ -n "$val" ]]; then
    echo "$key=$val" | sudo tee -a "$OUT" >/dev/null
  fi
done
echo "Synced secrets to $OUT"

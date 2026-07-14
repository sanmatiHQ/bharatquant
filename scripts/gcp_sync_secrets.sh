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
SSH_EXTRA=()
if [[ "${GCP_USE_IAP_SSH:-}" != "0" ]]; then
  SSH_EXTRA=(--tunnel-through-iap)
fi

_gssh() {
  gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" "${SSH_EXTRA[@]}" "$@"
}

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

PUBLIC_HOST="${BHARATQUANT_PUBLIC_HOST:-}"
if [[ -z "$PUBLIC_HOST" && -n "$STATIC_IP" ]]; then
  PUBLIC_HOST="${STATIC_IP//./-}.sslip.io"
fi

BUCKET="${GCS_BACKUP_BUCKET:-${PROJECT}-bharatquant}"
TMP_ENV=$(mktemp)
trap 'rm -f "$TMP_ENV"' EXIT

cp "$ROOT/deploy/bharatquant.env.production" "$TMP_ENV"
sed -i '' "s|__GCP_PROJECT_ID__|${PROJECT}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__GCP_PROJECT_ID__|${PROJECT}|g" "$TMP_ENV"
sed -i '' "s|__GCP_STATIC_IP__|${STATIC_IP}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__GCP_STATIC_IP__|${STATIC_IP}|g" "$TMP_ENV"
sed -i '' "s|__GCS_BACKUP_BUCKET__|${BUCKET}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__GCS_BACKUP_BUCKET__|${BUCKET}|g" "$TMP_ENV"
if [[ -n "$PUBLIC_HOST" ]]; then
  sed -i '' "s|__BHARATQUANT_PUBLIC_HOST__|${PUBLIC_HOST}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__BHARATQUANT_PUBLIC_HOST__|${PUBLIC_HOST}|g" "$TMP_ENV"
fi
sed -i '' "s|__KITE_API_KEY__|${KITE_API_KEY}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__KITE_API_KEY__|${KITE_API_KEY}|g" "$TMP_ENV"
sed -i '' "s|__KITE_API_SECRET__|${KITE_API_SECRET}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__KITE_API_SECRET__|${KITE_API_SECRET}|g" "$TMP_ENV"
sed -i '' "s|__KITE_USER_ID__|${KITE_USER_ID:-}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__KITE_USER_ID__|${KITE_USER_ID:-}|g" "$TMP_ENV"
sed -i '' "s|__KITE_PASSWORD__|${KITE_PASSWORD:-}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__KITE_PASSWORD__|${KITE_PASSWORD:-}|g" "$TMP_ENV"
sed -i '' "s|__KITE_TOTP_SECRET__|${KITE_TOTP_SECRET:-}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__KITE_TOTP_SECRET__|${KITE_TOTP_SECRET:-}|g" "$TMP_ENV"

# Gemini — local .env or GCP Secret Manager (gemini-api-key)
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  GEMINI_API_KEY=$(gcloud secrets versions access latest --secret=gemini-api-key --project="$PROJECT" 2>/dev/null || true)
fi
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  sed -i '' "s|__GEMINI_API_KEY__|${GEMINI_API_KEY}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__GEMINI_API_KEY__|${GEMINI_API_KEY}|g" "$TMP_ENV"
else
  echo "WARN: GEMINI_API_KEY missing — Vertex Gemini on VM will be primary"
fi
sed -i '' "s|^LLM_ENABLED=.*|LLM_ENABLED=true|" "$TMP_ENV" 2>/dev/null || sed -i "s|^LLM_ENABLED=.*|LLM_ENABLED=true|" "$TMP_ENV"
sed -i '' "s|^VERTEX_GEMINI_ENABLED=.*|VERTEX_GEMINI_ENABLED=true|" "$TMP_ENV" 2>/dev/null || sed -i "s|^VERTEX_GEMINI_ENABLED=.*|VERTEX_GEMINI_ENABLED=true|" "$TMP_ENV"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  OPENAI_API_KEY=$(gcloud secrets versions access latest --secret=openai-api-key --project="$PROJECT" 2>/dev/null || true)
fi
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  sed -i '' "s|__OPENAI_API_KEY__|${OPENAI_API_KEY}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__OPENAI_API_KEY__|${OPENAI_API_KEY}|g" "$TMP_ENV"
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  ANTHROPIC_API_KEY=$(gcloud secrets versions access latest --secret=anthropic-api-key --project="$PROJECT" 2>/dev/null || true)
fi
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  sed -i '' "s|__ANTHROPIC_API_KEY__|${ANTHROPIC_API_KEY}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__ANTHROPIC_API_KEY__|${ANTHROPIC_API_KEY}|g" "$TMP_ENV"
fi

# Dashboard owner credentials (single user)
DASH_PASS="${DASHBOARD_ADMIN_PASSWORD:-}"
DASH_USER="${DASHBOARD_ADMIN_USER:-owner}"
DASH_SESS="${DASHBOARD_SESSION_SECRET:-$DASH_PASS}"
if [[ -z "$DASH_PASS" ]]; then
  echo "WARN: DASHBOARD_ADMIN_PASSWORD empty — set in .env before cloud deploy"
  DASH_PASS="changeme-set-in-env"
fi
sed -i '' "s|__DASHBOARD_ADMIN_PASSWORD__|${DASH_PASS}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__DASHBOARD_ADMIN_PASSWORD__|${DASH_PASS}|g" "$TMP_ENV"
sed -i '' "s|__DASHBOARD_SESSION_SECRET__|${DASH_SESS}|g" "$TMP_ENV" 2>/dev/null || sed -i "s|__DASHBOARD_SESSION_SECRET__|${DASH_SESS}|g" "$TMP_ENV"
sed -i '' "s|^DASHBOARD_ADMIN_USER=.*|DASHBOARD_ADMIN_USER=${DASH_USER}|" "$TMP_ENV" 2>/dev/null || sed -i "s|^DASHBOARD_ADMIN_USER=.*|DASHBOARD_ADMIN_USER=${DASH_USER}|" "$TMP_ENV"

# Trading policy from local .env (non-secret overrides)
for key in DAILY_INVESTMENT_MIN DAILY_INVESTMENT_MAX BUDGET_APPROVAL_TIMEOUT_SEC ENGINE_24X7 TRADING_MODE; do
  val="${!key:-}"
  if [[ -n "$val" ]]; then
    sed -i '' "s|^${key}=.*|${key}=${val}|" "$TMP_ENV" 2>/dev/null || sed -i "s|^${key}=.*|${key}=${val}|" "$TMP_ENV"
  fi
done

echo "==> Upload /etc/bharatquant/env"
gcloud compute scp "${SSH_EXTRA[@]}" "$TMP_ENV" "${VM_NAME}:/tmp/bharatquant.env" --zone="$ZONE" --project="$PROJECT"
_gssh --command \
  "sudo mkdir -p /etc/bharatquant && sudo mv /tmp/bharatquant.env /etc/bharatquant/env && sudo chmod 640 /etc/bharatquant/env && sudo chown root:bharatquant /etc/bharatquant/env"

TOKEN_FILE="${KITE_ACCESS_TOKEN_FILE:-$ROOT/.kite_token.json}"
REMOTE_TOKEN="/var/lib/bharatquant/.kite_token.json"
SYNC_KITE_TOKEN="${SYNC_KITE_TOKEN:-0}"

_token_live_ok() {
  local path="$1"
  (cd "$ROOT" && KITE_ACCESS_TOKEN_FILE="$path" python3.11 -c "from src.ops.healthchecks import check_token; raise SystemExit(0 if check_token(live=True) else 1)") 2>/dev/null
}

if [[ -f "$TOKEN_FILE" ]]; then
  REMOTE_HAS=$(_gssh --command "test -f '$REMOTE_TOKEN' && echo yes || echo no" 2>/dev/null || echo "no")
  if [[ "$SYNC_KITE_TOKEN" == "1" ]]; then
    if _token_live_ok "$TOKEN_FILE"; then
      echo "==> Upload Kite token (SYNC_KITE_TOKEN=1, local token validated)"
      gcloud compute scp "${SSH_EXTRA[@]}" "$TOKEN_FILE" "${VM_NAME}:/tmp/.kite_token.json" --zone="$ZONE" --project="$PROJECT"
      _gssh --command \
        "sudo mv /tmp/.kite_token.json '$REMOTE_TOKEN' && sudo chown bharatquant:bharatquant '$REMOTE_TOKEN' && sudo chmod 600 '$REMOTE_TOKEN'"
    else
      echo "WARN: SYNC_KITE_TOKEN=1 but local token fails Kite validation — keeping VM token"
    fi
  elif [[ "$REMOTE_HAS" == "yes" ]]; then
    echo "==> Skip Kite token upload (VM OAuth token preserved; set SYNC_KITE_TOKEN=1 to push local)"
  elif _token_live_ok "$TOKEN_FILE"; then
    echo "==> Upload Kite token (VM has none; local token validated)"
    gcloud compute scp "${SSH_EXTRA[@]}" "$TOKEN_FILE" "${VM_NAME}:/tmp/.kite_token.json" --zone="$ZONE" --project="$PROJECT"
    _gssh --command \
      "sudo mv /tmp/.kite_token.json '$REMOTE_TOKEN' && sudo chown bharatquant:bharatquant '$REMOTE_TOKEN' && sudo chmod 600 '$REMOTE_TOKEN'"
  else
    echo "WARN: Local Kite token invalid — VM has no token; OAuth required at /login"
  fi
fi

echo "==> Secrets synced to $VM_NAME"
if [[ "${SKIP_SUPERVISOR_RESTART:-0}" != "1" ]]; then
  echo "==> Restart supervisor on VM"
  _gssh --command \
    "sudo systemctl restart bharatquant-supervisor && sleep 2 && systemctl is-active bharatquant-supervisor" || true
else
  echo "==> Skip supervisor restart (deploy bootstrap will reconcile stack)"
fi

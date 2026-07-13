#!/usr/bin/env bash
# Provision BharatQuant GCE VM + static IP + GCS bucket (asia-south1)
# Uses existing billing project — does NOT create a new GCP project.
#
# Usage:
#   bash scripts/gcp_provision.sh
#   GCP_PROJECT=your-gcp-project-id bash scripts/gcp_provision.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-${GCP_PROJECT_ID:-your-gcp-project-id}}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${GCP_ZONE:-asia-south1-a}"
VM_NAME="${VM_NAME:-bharatquant-engine}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-small}"
DISK_GB="${DISK_GB:-30}"
BUCKET="${GCS_BACKUP_BUCKET:-${PROJECT}-bharatquant}"
IP_NAME="${VM_NAME}-ip"

_need_gcloud() {
  if ! command -v gcloud &>/dev/null; then
    echo "ERROR: gcloud CLI not installed"
    exit 1
  fi
  if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1 | grep -q .; then
    echo "ERROR: gcloud not authenticated — run: gcloud auth login"
    exit 1
  fi
}

_need_gcloud
echo "==> Project $PROJECT"
gcloud config set project "$PROJECT" --quiet

echo "==> Enable APIs"
gcloud services enable compute.googleapis.com storage.googleapis.com --quiet

echo "==> GCS bucket gs://$BUCKET"
if ! gcloud storage buckets describe "gs://${BUCKET}" &>/dev/null; then
  gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" --uniform-bucket-level-access
fi

echo "==> Reserve static IP $IP_NAME"
if ! gcloud compute addresses describe "$IP_NAME" --region="$REGION" &>/dev/null; then
  gcloud compute addresses create "$IP_NAME" --region="$REGION"
fi
STATIC_IP=$(gcloud compute addresses describe "$IP_NAME" --region="$REGION" --format='get(address)')
echo "STATIC_IP=$STATIC_IP"

STARTUP="#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3.11 python3.11-venv python3-pip git curl sqlite3
mkdir -p /opt/bharatquant /var/lib/bharatquant /var/log/bharatquant /etc/bharatquant
id bharatquant &>/dev/null || useradd -r -m -d /home/bharatquant -s /bin/bash bharatquant
chown -R bharatquant:bharatquant /opt/bharatquant /var/lib/bharatquant /var/log/bharatquant
echo bharatquant-vm-ready > /var/log/bharatquant/startup.done
"

if gcloud compute instances describe "$VM_NAME" --zone="$ZONE" &>/dev/null; then
  echo "==> VM $VM_NAME already exists — skipping create"
else
  echo "==> Create VM $VM_NAME ($MACHINE_TYPE, ${DISK_GB}GB)"
  gcloud compute instances create "$VM_NAME" \
    --zone="$ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size="${DISK_GB}GB" \
    --address="$STATIC_IP" \
    --scopes=storage-full,cloud-platform \
    --tags=bharatquant \
    --metadata=enable-oslogin=TRUE,startup-script="$STARTUP"
fi

echo "==> Firewall: SSH + dashboard 8080 + HTTPS 80/443"
if ! gcloud compute firewall-rules describe bharatquant-allow-dashboard &>/dev/null; then
  gcloud compute firewall-rules create bharatquant-allow-dashboard \
    --allow=tcp:8080,tcp:22,tcp:80,tcp:443 \
    --target-tags=bharatquant \
    --description="BharatQuant dashboard + SSH + Caddy TLS"
else
  gcloud compute firewall-rules update bharatquant-allow-dashboard \
    --allow=tcp:8080,tcp:22,tcp:80,tcp:443 2>/dev/null || true
fi

# Persist for local deploy scripts
STATE_FILE="$ROOT/.gcp_state.env"
cat > "$STATE_FILE" <<EOF
GCP_PROJECT_ID=$PROJECT
GCP_REGION=$REGION
GCP_ZONE=$ZONE
VM_NAME=$VM_NAME
GCP_STATIC_IP=$STATIC_IP
GCS_BACKUP_BUCKET=$BUCKET
EOF
chmod 600 "$STATE_FILE"

echo ""
echo "=== PROVISIONED ==="
cat "$STATE_FILE"
echo ""
echo "NEXT: bash scripts/gcp_deploy.sh   # push code + secrets + bootstrap"
echo "Kite whitelist IP: $STATIC_IP  →  https://developers.kite.trade"
echo "Redirect URL: https://\${BHARATQUANT_PUBLIC_HOST:-YOUR_PUBLIC_HOST.sslip.io}/kite/callback  (HTTPS — Kite requires this)"

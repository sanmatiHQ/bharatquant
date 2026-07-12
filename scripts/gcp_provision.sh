#!/usr/bin/env bash
# Provision BharatQuant GCE VM + static IP + GCS bucket (asia-south1)
# Usage: GCP_PROJECT=your-project-id bash scripts/gcp_provision.sh
set -euo pipefail

PROJECT="${GCP_PROJECT:-bharatquant-prod}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${GCP_ZONE:-asia-south1-a}"
VM_NAME="${VM_NAME:-bharatquant-engine}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-small}"
DISK_GB="${DISK_GB:-20}"
BUCKET="${GCS_BACKUP_BUCKET:-${PROJECT}-bharatquant}"

echo "==> Project $PROJECT"
gcloud projects create "$PROJECT" --name="BharatQuant" 2>/dev/null || true
gcloud config set project "$PROJECT"

echo "==> GCS bucket gs://$BUCKET"
gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" 2>/dev/null || true

echo "==> Reserve static IP"
gcloud compute addresses create "${VM_NAME}-ip" --region="$REGION" 2>/dev/null || true
STATIC_IP=$(gcloud compute addresses describe "${VM_NAME}-ip" --region="$REGION" --format='get(address)')
echo "STATIC_IP=$STATIC_IP"

STARTUP=$(cat <<'SCRIPT'
#!/bin/bash
set -e
apt-get update -qq
apt-get install -y python3.11 python3.11-venv git
mkdir -p /opt/bharatquant /var/lib/bharatquant /var/log/bharatquant
useradd -r -m bharatquant 2>/dev/null || true
SCRIPT
)

echo "==> Create VM with static IP"
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

echo "==> Firewall: SSH + dashboard 8080"
gcloud compute firewall-rules create bharatquant-allow-dashboard \
  --allow=tcp:8080,tcp:22 \
  --target-tags=bharatquant \
  --description="BharatQuant dashboard" 2>/dev/null || true

echo ""
echo "=== PROVISIONED ==="
echo "STATIC_IP=$STATIC_IP"
echo "GCS_BACKUP_BUCKET=$BUCKET"
echo ""
echo "NEXT STEPS:"
echo "1. Billing: https://console.cloud.google.com/billing → attach to $PROJECT"
echo "2. Kite whitelist: https://developers.kite.trade → IP → $STATIC_IP"
echo "3. SSH: gcloud compute ssh $VM_NAME --zone=$ZONE"
echo "4. Clone: git clone https://github.com/sanmatiHQ/bharatquant.git /opt/bharatquant/zerodha-momo-rl"
echo "5. Env: cp .env.example /etc/bharatquant/env — set KITE_*, GCS_BACKUP_BUCKET=$BUCKET, GCP_STATIC_IP=$STATIC_IP"
echo "6. Install units:"
echo "   sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/"
echo "   sudo systemctl enable bharatquant-supervisor bharatquant-rl-train.timer"
echo "   sudo systemctl start bharatquant-supervisor"
echo "7. Redirect URL: http://${STATIC_IP}:8080/kite/callback"

#!/usr/bin/env bash
# Provision BharatQuant GCE VM on GCP (asia-south1)
# Usage: GCP_PROJECT=bharatquant-prod bash scripts/gcp_provision.sh
set -euo pipefail

PROJECT="${GCP_PROJECT:-bharatquant-prod}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${GCP_ZONE:-asia-south1-a}"
VM_NAME="${VM_NAME:-bharatquant-engine}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-small}"
DISK_GB="${DISK_GB:-20}"

echo "==> Creating GCP project (link billing manually in console if new)"
gcloud projects create "$PROJECT" --name="BharatQuant" 2>/dev/null || true
gcloud config set project "$PROJECT"

echo "==> Reserve static IP"
gcloud compute addresses create "${VM_NAME}-ip" --region="$REGION" || true
STATIC_IP=$(gcloud compute addresses describe "${VM_NAME}-ip" --region="$REGION" --format='get(address)')
echo "STATIC_IP=$STATIC_IP  <-- whitelist this at developers.kite.trade"

echo "==> Create VM with static IP"
gcloud compute instances create "$VM_NAME" \
  --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size="${DISK_GB}GB" \
  --address="$STATIC_IP" \
  --tags=bharatquant \
  --metadata=enable-oslogin=TRUE

echo "==> Firewall: SSH + dashboard 8080 (restrict to your IP in production)"
gcloud compute firewall-rules create bharatquant-allow-dashboard \
  --allow=tcp:8080,tcp:22 \
  --target-tags=bharatquant \
  --description="BharatQuant dashboard" 2>/dev/null || true

echo ""
echo "=== NEXT STEPS ==="
echo "1. Link billing: https://console.cloud.google.com/billing — attach to $PROJECT"
echo "2. Zerodha whitelist: https://developers.kite.trade → Profile → IP Whitelist → $STATIC_IP"
echo "3. SSH: gcloud compute ssh $VM_NAME --zone=$ZONE"
echo "4. Clone repo + copy .env from .env.example"
echo "5. Secret Manager for KITE_* and TOTP (evening checklist in docs/EVOLUTION_LOG.md)"

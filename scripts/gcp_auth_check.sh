#!/usr/bin/env bash
# Preflight before GCP deploy — ensures gcloud auth + project access.
set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-your-gcp-project-id}"

if ! command -v gcloud &>/dev/null; then
  echo "Install: https://cloud.google.com/sdk/docs/install"
  exit 1
fi

ACCT=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1 || true)
if [[ -z "$ACCT" ]]; then
  echo "No active gcloud account. Run:"
  echo "  gcloud auth login"
  echo "  gcloud config set project $PROJECT"
  exit 1
fi

if ! gcloud auth print-access-token &>/dev/null; then
  echo "gcloud token expired for $ACCT. Run:"
  echo "  gcloud auth login"
  exit 1
fi

gcloud config set project "$PROJECT" --quiet
echo "OK: $ACCT @ $PROJECT"
gcloud services list --enabled --filter="name:compute.googleapis.com" --format='value(name)' | head -1

#!/usr/bin/env bash
# BharatQuant — market supervisor arms engine on activity (no manual start)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONUNBUFFERED=1

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

mkdir -p "${LOGS_DIR:-logs}" data

# Supervisor starts engine + dashboard when market/GIFT activity detected
# Paper mode: PAPER_ALWAYS_ON=true keeps stack running for autonomous paper trading
exec python3.11 -m src.ops.market_supervisor

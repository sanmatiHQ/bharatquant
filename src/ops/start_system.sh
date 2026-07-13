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

# Supervisor starts engine + dashboard — 24×7 learn mode (ENGINE_24X7=true)
# Paper mode: PAPER_ALWAYS_ON=true also keeps stack running
# macOS auto-start on login: bash scripts/install_launch_agent.sh
exec python3.11 -m src.ops.market_supervisor

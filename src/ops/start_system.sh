#!/usr/bin/env bash
# BharatQuant — event-driven engine + FastAPI dashboard (no cron, no Flask stubs)
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

python3.11 -m src.engine.main &
ENGINE_PID=$!
python3.11 -m src.api.dashboard &
DASH_PID=$!

trap 'kill $ENGINE_PID $DASH_PID 2>/dev/null' EXIT INT TERM
wait

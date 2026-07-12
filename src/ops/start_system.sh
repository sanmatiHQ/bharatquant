#!/usr/bin/env bash
# BharatQuant — event-driven engine + FastAPI dashboard (no cron, no Flask stubs)
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1

python3.11 -m src.engine.main &
ENGINE_PID=$!
python3.11 -m src.api.dashboard &
DASH_PID=$!

trap 'kill $ENGINE_PID $DASH_PID 2>/dev/null' EXIT INT TERM
wait

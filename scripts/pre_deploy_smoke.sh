#!/usr/bin/env bash
# Block deploy if engine/supervisor cannot boot locally.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> pre_deploy_smoke: pytest"
python3.11 -m pytest tests/ -q --tb=line -x

echo "==> pre_deploy_smoke: engine import + API contract"
python3.11 - <<'PY'
import inspect
import importlib

import src.engine.main as engine_main
import src.ops.market_supervisor as sup
import src.ops.kite_token_watcher as tw
from src.ops.agent_state import persist_engine_phase

sig = inspect.signature(persist_engine_phase)
assert len(sig.parameters) == 1, f"persist_engine_phase arity wrong: {sig}"
assert hasattr(engine_main, "main")
assert hasattr(sup, "_bootstrap_stack")
assert hasattr(tw, "watch_kite_token_file")
print("boot_contract_ok")
PY

echo "==> pre_deploy_smoke: compile critical modules"
python3.11 -m py_compile \
  src/engine/main.py \
  src/ops/market_supervisor.py \
  src/ops/kite_token_watcher.py \
  src/ops/healthchecks.py \
  src/api/dashboard.py

echo "==> pre_deploy_smoke: PASS"

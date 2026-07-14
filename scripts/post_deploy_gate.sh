#!/usr/bin/env bash
# Hard gate after gcp_deploy — fail deploy if stack not healthy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STATE_FILE="$ROOT/.gcp_state.env"
# shellcheck disable=SC1090
[[ -f "$STATE_FILE" ]] && source "$STATE_FILE"

PROJECT="${GCP_PROJECT_ID:-your-gcp-project-id}"
ZONE="${GCP_ZONE:-asia-south1-a}"
VM_NAME="${VM_NAME:-bharatquant-engine}"
PUBLIC_HOST="${BHARATQUANT_PUBLIC_HOST:-}"
if [[ -z "$PUBLIC_HOST" && -n "${GCP_STATIC_IP:-}" ]]; then
  PUBLIC_HOST="${GCP_STATIC_IP//./-}.sslip.io"
fi
BASE_URL="https://${PUBLIC_HOST}"

SSH_OPTS=(--tunnel-through-iap)
_ssh() { gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" "${SSH_OPTS[@]}" "$@"; }

fail() { echo "GATE FAIL: $1"; exit 1; }
ok() { echo "GATE OK: $1"; }

echo "==> post_deploy_gate: wait for stack (up to 90s)"
for i in $(seq 1 18); do
  LOCAL=$(_ssh --command "curl -sf -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health" 2>/dev/null || echo "000")
  HTTPS=$(curl -sk -o /dev/null -w "%{http_code}" "${BASE_URL}/health" 2>/dev/null || echo "000")
  if [[ "$LOCAL" == "200" && "$HTTPS" == "200" ]]; then
    ok "health local=$LOCAL https=$HTTPS (${i}*5s)"
    break
  fi
  if [[ "$i" -eq 18 ]]; then
    fail "health not 200 after 90s (local=$LOCAL https=$HTTPS)"
  fi
  sleep 5
done

_count_module() {
  _ssh --command "pgrep -f '^/usr/bin/python3.11 -m ${1}\$' 2>/dev/null | wc -l" 2>/dev/null | tr -d '[:space:]'
}

DASH_COUNT=$(_count_module "src.api.dashboard")
ENGINE_COUNT=$(_count_module "src.engine.main")
if [[ "${DASH_COUNT:-0}" -eq 0 || "${ENGINE_COUNT:-0}" -eq 0 ]]; then
  for _w in $(seq 1 6); do
    sleep 5
    DASH_COUNT=$(_count_module "src.api.dashboard")
    ENGINE_COUNT=$(_count_module "src.engine.main")
    [[ "${DASH_COUNT:-0}" -ge 1 && "${ENGINE_COUNT:-0}" -ge 1 ]] && break
  done
fi
[[ "${DASH_COUNT:-0}" -ge 1 ]] || fail "dashboard not running (count=$DASH_COUNT)"
[[ "${ENGINE_COUNT:-0}" -ge 1 ]] || fail "engine not running (count=$ENGINE_COUNT)"
if [[ "${DASH_COUNT:-0}" -gt 1 || "${ENGINE_COUNT:-0}" -gt 1 ]]; then
  warn_msg="duplicate PIDs dashboard=$DASH_COUNT engine=$ENGINE_COUNT (supervisor will dedupe)"
  echo "GATE WARN: $warn_msg"
fi
ok "single dashboard + engine"

BIND_ERRS=$(_ssh --command "tail -30 /var/log/bharatquant/src_api_dashboard.log 2>/dev/null | grep -c 'address already in use' || echo 0" 2>/dev/null | tr -d '[:space:]')
[[ "${BIND_ERRS:-0}" -eq 0 ]] || fail "dashboard port bind errors in last 30 log lines ($BIND_ERRS)"
ok "no recent port-8080 bind errors"

HB_AGE=$(_ssh --command "sudo -u bharatquant bash -lc 'set -a; source /etc/bharatquant/env; set +a; cd /opt/bharatquant/zerodha-momo-rl; python3.11 -c \"import os,time; from src.db.database import DB,DBConfig; db=DB(DBConfig(sqlite_path=os.environ[\\\"SQLITE_PATH\\\"])); r=db._conn.execute(\\\"SELECT v FROM settings WHERE k=\\\\\\\"engine_heartbeat_ts\\\\\\\"\\\").fetchone(); print(int(time.time())-int(r[\\\"v\\\"])) if r and str(r[\\\"v\\\"]).isdigit() else 9999\"'" 2>/dev/null || echo "9999")
[[ "${HB_AGE:-9999}" -lt 120 ]] || fail "engine heartbeat stale ${HB_AGE}s"
ok "engine heartbeat ${HB_AGE}s"

AUTH=$(_ssh --command "curl -sf http://127.0.0.1:8080/api/auth/status" 2>/dev/null || echo '{}')
python3.11 - "$AUTH" <<'PY' || fail "kite token invalid after deploy (re-login at /login)"
import json, sys
d = json.loads(sys.argv[1])
if d.get("valid"):
    print("kite_token_valid")
    sys.exit(0)
# Token may be absent on fresh VM — warn only
if not d.get("saved_ts"):
    print("kite_token_absent_warn")
    sys.exit(0)
sys.exit(1)
PY
ok "kite auth status"

CODE=$(curl -sk -o /dev/null -w "%{http_code}" "${BASE_URL}/dashboard" 2>/dev/null || echo "000")
[[ "$CODE" == "200" ]] || fail "HTTPS /dashboard → $CODE"
ok "HTTPS dashboard 200"

echo "==> post_deploy_gate: layer6 structural proof"
_ssh --command "sudo -u bharatquant bash -lc 'set -a; source /etc/bharatquant/env; set +a; cd /opt/bharatquant/zerodha-momo-rl; python3.11 scripts/prove_layer6_vm.py'" || fail "prove_layer6_vm.py"
ok "layer6 capital gate proof"

echo "==> post_deploy_gate: ALL PASS"

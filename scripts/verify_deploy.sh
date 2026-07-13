#!/usr/bin/env bash
# Full deployment verification — local tests + VM health/API/probes.
# Usage: bash scripts/verify_deploy.sh [--redeploy] [--no-redeploy]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT_ID:-your-gcp-project-id}"
ZONE="${GCP_ZONE:-asia-south1-a}"
VM_NAME="${VM_NAME:-bharatquant-engine}"
PUBLIC_HOST="${BHARATQUANT_PUBLIC_HOST:-your-public-host.sslip.io}"
BASE_URL="https://${PUBLIC_HOST}"
REPORT="/tmp/bharatquant_verify_$$.json"

SSH_OPTS=(--tunnel-through-iap)
_ssh() { gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" "${SSH_OPTS[@]}" "$@"; }

PASS=0
FAIL=0
WARN=0

pass() { echo "  PASS  $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL  $1"; FAIL=$((FAIL + 1)); }
warn() { echo "  WARN  $1"; WARN=$((WARN + 1)); }

echo "=== BharatQuant deploy verification ==="
echo "Time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

echo "== [1/6] Local pytest =="
if python3.11 -m pytest tests/ -q --tb=line 2>&1 | tee /tmp/bq_pytest.log | tail -3 | grep -q "passed"; then
  pass "pytest suite green ($(tail -1 /tmp/bq_pytest.log))"
else
  fail "pytest suite — see /tmp/bq_pytest.log"
fi

echo ""
echo "== [2/6] Required files on disk =="
REQUIRED=(
  src/intelligence/institutional_learning.py
  src/intelligence/event_outcomes.py
  src/intelligence/institutional_entities.py
  src/ingest/nse_shareholding.py
  src/strategies/bulk_distribution.py
  src/strategies/institutional_flow.py
  scripts/probe_institutional_learning.py
  src/ops/session_ledger.py
  src/intelligence/corporate_activity.py
)
for f in "${REQUIRED[@]}"; do
  if [[ -f "$ROOT/$f" ]]; then pass "local $f"; else fail "missing local $f"; fi
done

echo ""
echo "== [3/6] Local synthetic institutional proof =="
if python3.11 scripts/probe_institutional_learning.py 2>&1 | tee /tmp/bq_inst_proof.log | grep -q "ALL CHECKS PASSED"; then
  pass "probe_institutional_learning synthetic"
else
  fail "probe_institutional_learning synthetic"
fi

echo ""
echo "== [4/6] VM file parity (critical modules) =="
VM_MISSING=""
for f in "${REQUIRED[@]}"; do
  if _ssh --command "test -f /opt/bharatquant/zerodha-momo-rl/$f" 2>/dev/null; then
    pass "VM $f"
  else
    fail "VM missing $f"
    VM_MISSING=1
  fi
done

echo ""
echo "== [5/6] VM HTTP + API checks =="
# Health (direct IP:8080 on VM)
HEALTH=$(_ssh --command "curl -sf http://127.0.0.1:8080/health" 2>/dev/null || echo '{}')
if echo "$HEALTH" | python3.11 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ok') or d.get('status')=='ok' or 'db' in d" 2>/dev/null; then
  pass "GET /health → $HEALTH"
else
  fail "GET /health — $HEALTH"
fi

# Public HTTPS dashboard
CODE=$(curl -sk -o /tmp/bq_dash.html -w "%{http_code}" "${BASE_URL}/dashboard" 2>/dev/null || echo "000")
if [[ "$CODE" == "200" ]]; then
  pass "GET /dashboard → 200"
else
  fail "GET /dashboard → $CODE"
fi

if grep -q "renderSandbox" /tmp/bq_dash.html 2>/dev/null; then
  pass "dashboard HTML has renderSandbox (JS fix)"
else
  fail "dashboard missing renderSandbox"
fi

if grep -q "learnBadge" /tmp/bq_dash.html 2>/dev/null; then
  pass "dashboard HTML has learnBadge"
else
  fail "dashboard missing learnBadge"
fi

if grep -q "sessionLedger\|plan_for_tomorrow\|Today's ledger" /tmp/bq_dash.html 2>/dev/null; then
  pass "dashboard has session ledger panel"
else
  warn "session ledger panel string not found in HTML (may use different label)"
fi

# Fast feed JSON
FEED=$(curl -sk "${BASE_URL}/api/feed/fast" 2>/dev/null || echo '{}')
python3.11 - "$FEED" "$REPORT" <<'PY' 2>/dev/null || true
import json, sys
raw = sys.argv[1]
out = {}
try:
    f = json.loads(raw)
except Exception:
    f = {}
checks = {
    "has_session": "session" in f and isinstance(f.get("session"), dict),
    "has_corporate": "corporate" in f,
    "has_institutional_learning": "institutional_learning" in f,
    "has_pnl": f.get("session", {}).get("pnl") is not None if isinstance(f.get("session"), dict) else False,
    "has_plan": bool((f.get("session") or {}).get("plan_for_tomorrow")),
}
out["feed_checks"] = checks
out["trade_count"] = (f.get("session") or {}).get("trade_count")
out["labeled_outcomes"] = (f.get("institutional_learning") or {}).get("labeled_outcomes")
out["rl_transitions_feed"] = (f.get("institutional_learning") or {}).get("rl_transitions")
out["corporate_counts"] = (f.get("corporate") or {}).get("counts")
with open(sys.argv[2], "w") as fh:
    json.dump(out, fh, indent=2)
for k, v in checks.items():
    print(f"FEED_{k}={v}")
PY

if grep -q "FEED_has_session=True" /dev/stderr 2>/dev/null || python3.11 -c "import json; d=json.load(open('$REPORT')); assert d['feed_checks']['has_session']" 2>/dev/null; then
  :
fi
# Re-read report for pass/fail
if python3.11 -c "
import json, sys
d=json.load(open('$REPORT'))
c=d['feed_checks']
for k,v in c.items():
    print(f'  {\"PASS\" if v else \"FAIL\"}  feed.{k}')
    sys.exit(1 if not all(c.values()) else 0)
" 2>&1; then
  pass "fast feed schema complete"
else
  python3.11 -c "
import json
d=json.load(open('$REPORT'))
for k,v in d['feed_checks'].items():
    if not v: print('  FAIL  feed.'+k)
" || true
  fail "fast feed missing required keys — see $REPORT"
fi

echo "Feed snapshot: $(cat "$REPORT" 2>/dev/null || echo '{}')"

echo "== [6/6] VM probes (DB + live NSE) =="
PROBE_DB=$(_ssh --command "sudo -u bharatquant bash -lc 'cd /opt/bharatquant/zerodha-momo-rl && set -a && source /etc/bharatquant/env && set +a && python3.11 scripts/probe_institutional_learning.py --db'" 2>&1 || echo "PROBE_FAIL")
if echo "$PROBE_DB" | grep -q "PASS  DB proof"; then
  pass "VM probe_institutional_learning --db"
  echo "$PROBE_DB" | grep -E '"(ingest_types|shareholding_rows|rl_transitions|outcomes_labeled)"' | head -6 || true
else
  fail "VM probe_institutional_learning --db"
  echo "$PROBE_DB" | tail -20
fi

LIVE=$(_ssh --command "sudo -u bharatquant bash -lc 'cd /opt/bharatquant/zerodha-momo-rl && set -a && source /etc/bharatquant/env && set +a && python3.11 scripts/probe_institutional_learning.py --live RELIANCE 2>&1 | grep -E \"PASS|promoter_pct|FAIL\" | head -5'" 2>&1 || echo "LIVE_FAIL")
if echo "$LIVE" | grep -q "live shareholding"; then
  pass "VM live NSE shareholding fetch"
else
  fail "VM live NSE shareholding — $LIVE"
fi

# Supervisor / engine process
SUP=$(_ssh --command "systemctl is-active bharatquant-supervisor 2>/dev/null; pgrep -f '/usr/bin/python3.11 -m src.engine.main' | wc -l" 2>&1 || true)
ENGINE_COUNT=$(echo "$SUP" | tail -1 | tr -d '[:space:]')
if echo "$SUP" | grep -q "^active"; then
  pass "bharatquant-supervisor systemd active"
else
  warn "bharatquant-supervisor not active — $SUP"
fi
if [[ "${ENGINE_COUNT:-0}" -eq 1 ]]; then
  pass "single engine process (count=1)"
elif [[ "${ENGINE_COUNT:-0}" -eq 0 ]]; then
  warn "no engine process running"
else
  fail "duplicate engine processes (count=$ENGINE_COUNT)"
fi

HB_AGE=$(_ssh --command "sudo -u bharatquant bash -lc 'cd /opt/bharatquant/zerodha-momo-rl && set -a && source /etc/bharatquant/env && set +a && python3.11 -c \"import os,time; from src.db.database import DB,DBConfig; db=DB(DBConfig(sqlite_path=os.environ[\\\"SQLITE_PATH\\\"])); r=db._conn.execute(\\\"SELECT v FROM settings WHERE k=\\\\\\\"engine_heartbeat_ts\\\\\\\"\\\").fetchone(); print(int(time.time())-int(r[\\\"v\\\"])) if r and str(r[\\\"v\\\"]).isdigit() else 9999\"'" 2>/dev/null || echo "9999")
if [[ "${HB_AGE:-9999}" -lt 120 ]]; then
  pass "engine heartbeat age ${HB_AGE}s (<120)"
else
  fail "engine heartbeat stale ${HB_AGE}s (ENGINE DOWN pill)"
fi

echo ""
echo "== [7/7] VM ingest proof (one-shot NSE fetch) =="
INGEST=$(_ssh --command "sudo -u bharatquant bash -lc 'cd /opt/bharatquant/zerodha-momo-rl && set -a && source /etc/bharatquant/env && set +a && python3.11 scripts/prove_ingest_vm.py'" 2>&1 || echo "INGEST_FAIL")
if echo "$INGEST" | grep -q "PASS prove_ingest"; then
  pass "prove_ingest_vm (bulk+insider+shareholding)"
  echo "$INGEST" | grep -E "PASS|total_" | head -6
else
  fail "prove_ingest_vm — $INGEST"
fi

echo ""
echo "=== SUMMARY: PASS=$PASS FAIL=$FAIL WARN=$WARN ==="

if [[ "$FAIL" -gt 0 ]] || [[ -n "${VM_MISSING:-}" ]]; then
  if [[ "${1:-}" == "--redeploy" ]]; then
    echo ""
    echo "==> Redeploying (gcp_deploy.sh) =="
    bash "$ROOT/scripts/gcp_deploy.sh"
    echo ""
    echo "==> Re-verify after redeploy (no second redeploy) =="
    sleep 20
    exec bash "$0" --no-redeploy
  else
    echo "Run: bash scripts/verify_deploy.sh --redeploy"
    exit 1
  fi
fi

if [[ "$WARN" -gt 0 ]]; then
  exit 0
fi
exit 0

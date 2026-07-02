#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# KubeSynapse — Incident Auto-Triage Demo (End-to-End)
# ────────────────────────────────────────────────────────────────────
# This script runs the complete "wow" demo:
#   1. Builds and loads the demo app image (Flask with memory leak)
#   2. Deploys the broken checkout-api (64Mi memory limit → OOMKilled)
#   3. Sends traffic to trigger the memory leak and OOMKilled crash
#   4. Fires an Alertmanager webhook to create an incident
#   5. Triggers the incident-auto-triage AgentWorkflow
#   6. Waits for the workflow to complete
#   7. Retrieves and displays the incident report
#
# Usage:
#   ./scripts/incidents/trigger-incident-triage.sh
#   ./scripts/incidents/trigger-incident-triage.sh --skip-build   # skip image build
#   ./scripts/incidents/trigger-incident-triage.sh --skip-deploy   # skip app deploy
#   ./scripts/incidents/trigger-incident-triage.sh --skip-alert    # just trigger workflow
#   ./scripts/incidents/trigger-incident-triage.sh --cleanup       # remove demo app after
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEMO_APP_DIR="${REPO_ROOT}/examples/incident-auto-triage/demo-app"

# ── Colors ──────────────────────────────────────────────────────────
RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; NC=$'\033[0m'
info() { echo "${BLUE}[INFO]${NC}  $*"; }
ok()   { echo "${GREEN}[OK]${NC}    $*"; }
warn() { echo "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo "${RED}[ERROR]${NC} $*" >&2; }
step() { echo ""; echo -e "${CYAN}${BOLD}═══ $* ═══${NC}"; }

# ── Defaults ────────────────────────────────────────────────────────
NAMESPACE="default"
WORKFLOW_NAME="incident-auto-triage"
WORKFLOW_INPUT="Alertmanager firing: PodOOMKilled on checkout-api in default namespace. Pod checkout-api has restarted 5+ times with OOMKilled (exit code 137). Memory limit is 64Mi. Triage the incident, investigate the live cluster, diagnose root cause, and produce a safe remediation plan with an operator-ready kubectl command and declarative patch YAML."
SKIP_BUILD=false
SKIP_DEPLOY=false
SKIP_ALERT=false
CLEANUP=false
WAIT_SECONDS=300

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace)    NAMESPACE="$2"; shift 2 ;;
    --workflow)     WORKFLOW_NAME="$2"; shift 2 ;;
    --input)        WORKFLOW_INPUT="$2"; shift 2 ;;
    --wait)         WAIT_SECONDS="$2"; shift 2 ;;
    --skip-build)   SKIP_BUILD=true; shift ;;
    --skip-deploy)  SKIP_DEPLOY=true; shift ;;
    --skip-alert)   SKIP_ALERT=true; shift ;;
    --cleanup)      CLEANUP=true; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

# ── Resolve gateway URL & token ─────────────────────────────────────
GATEWAY_PORT=8080
GATEWAY_URL="${KUBESYNAPSE_GATEWAY_URL:-}"

if [[ -z "${GATEWAY_URL}" ]]; then
  if ! ss -lnt 2>/dev/null | grep -q ":${GATEWAY_PORT} "; then
    info "No listener on port ${GATEWAY_PORT} — starting port-forward to kubesynapse-api-gateway"
    kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway "${GATEWAY_PORT}:8080" >/tmp/kubesynapse-pf-triage.log 2>&1 &
    sleep 4
  fi
  GATEWAY_URL="http://127.0.0.1:${GATEWAY_PORT}"
fi

TOKEN="${KUBESYNAPSE_API_TOKEN:-}"
if [[ -z "${TOKEN}" ]]; then
  TOKEN="$(kubectl get secret kubesynapse-llm-api-keys -n kubesynapse -o jsonpath='{.data.API_GATEWAY_SHARED_TOKEN}' 2>/dev/null | base64 --decode 2>/dev/null || true)"
  [[ -n "${TOKEN}" ]] && ok "Loaded gateway token from kubesynapse-llm-api-keys"
fi
if [[ -z "${TOKEN}" ]]; then
  TOKEN="$(kubectl get secret kubesynapse-shared-auth -n kubesynapse -o jsonpath='{.data.token}' 2>/dev/null | base64 --decode 2>/dev/null || true)"
fi
if [[ -z "${TOKEN}" ]]; then
  err "Could not resolve KUBESYNAPSE_API_TOKEN. Set the env var or install the platform with a shared token secret."
  exit 1
fi

# ── Upgrade to admin JWT (shared token has viewer role) ──────────────
ADMIN_PASS="$(kubectl get secret kubesynapse-llm-api-keys -n kubesynapse -o jsonpath='{.data.AUTH_BOOTSTRAP_ADMIN_PASSWORD}' 2>/dev/null | base64 --decode 2>/dev/null || true)"
if [[ -n "${ADMIN_PASS}" ]]; then
  JWT_TOKEN="$(python3 -c "
import json, urllib.request
body = json.dumps({'username': 'admin', 'password': '${ADMIN_PASS}'}).encode()
req = urllib.request.Request('${GATEWAY_URL}/api/v1/auth/login', data=body, headers={'Content-Type': 'application/json'})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    d = json.loads(resp.read())
    print(d.get('access_token', ''))
except Exception:
    print('')
" 2>/dev/null || true)"
  if [[ -n "${JWT_TOKEN}" ]]; then
    ok "Authenticated as admin (JWT)"
    TOKEN="${JWT_TOKEN}"
  else
    warn "Admin login failed -- using shared token (may lack operator role)"
  fi
else
  warn "AUTH_BOOTSTRAP_ADMIN_PASSWORD not found -- using shared token"
fi

# ════════════════════════════════════════════════════════════════════
# STEP 1: Build and load the demo app image
# ════════════════════════════════════════════════════════════════════
if [[ "${SKIP_BUILD}" == "false" ]]; then
  step "Step 1/7: Building Demo App Image"
  echo "  App: checkout-api (Flask with intentional memory leak)"

  docker build -t localhost/kubesynapse/checkout-api:demo "${DEMO_APP_DIR}" 2>&1 | tail -3
  kind load docker-image localhost/kubesynapse/checkout-api:demo --name kubesynapse-dev 2>&1 | grep -v "^Reading package" || true
  ok "Demo app image loaded into kind"
else
  info "Skipping image build (--skip-build)"
fi

# ════════════════════════════════════════════════════════════════════
# STEP 2: Deploy the broken checkout-api
# ════════════════════════════════════════════════════════════════════
if [[ "${SKIP_DEPLOY}" == "false" ]]; then
  step "Step 2/7: Deploying Broken Checkout API"
  echo "  Memory limit: 64Mi (intentionally too low)"
  echo "  Memory leak: 10MB per /checkout request"

  kubectl apply -f "${DEMO_APP_DIR}/manifests.yaml" 2>&1
  info "Waiting for checkout-api pod to be ready..."
  kubectl wait --for=condition=ready pod -l app=checkout-api -n "${NAMESPACE}" --timeout=60s 2>&1 || {
    warn "Pod not ready in 60s — checking status..."
    kubectl get pods -l app=checkout-api -n "${NAMESPACE}"
  }
  ok "checkout-api deployed"
  kubectl get pods -l app=checkout-api -n "${NAMESPACE}"
else
  info "Skipping app deploy (--skip-deploy)"
fi

# ════════════════════════════════════════════════════════════════════
# STEP 3: Send traffic to trigger OOMKilled
# ════════════════════════════════════════════════════════════════════
step "Step 3/7: Triggering Memory Leak → OOMKilled"
echo "  Sending 10 checkout requests (10MB each) to exhaust 64Mi limit..."

# Port-forward to the checkout-api service
kubectl port-forward -n "${NAMESPACE}" svc/checkout-api 18080:80 >/tmp/kubesynapse-pf-checkout.log 2>&1 &
PF_PID=$!
sleep 3

REQUESTS_SENT=0
for i in $(seq 1 10); do
  HTTP_CODE=$(curl -sS -o /tmp/checkout-response.json -w "%{http_code}" \
    -X POST "http://127.0.0.1:18080/checkout" --max-time 5 2>/dev/null || echo "000")
  if [[ "${HTTP_CODE}" == "200" ]]; then
    REQUESTS_SENT=$((REQUESTS_SENT + 1))
    LEAKED_MB=$(python3 -c "import json; d=json.load(open('/tmp/checkout-response.json')); print(d.get('leaked_memory_mb', '?'))" 2>/dev/null || echo "?")
    echo "  Request ${i}: 200 OK — leaked ${LEAKED_MB}MB total"
  else
    echo "  Request ${i}: HTTP ${HTTP_CODE} — pod may be OOMKilled"
    break
  fi
  sleep 0.5
done

kill ${PF_PID} 2>/dev/null || true
ok "Sent ${REQUESTS_SENT} requests — waiting for OOMKilled..."

# Wait for the pod to get OOMKilled and restart
sleep 5
echo ""
echo "  Pod status after traffic:"
kubectl get pods -l app=checkout-api -n "${NAMESPACE}" -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[0].restartCount,LAST-STATE:.status.containerStatuses[0].lastState.terminated.reason 2>&1

# Check for OOMKilled events
echo ""
echo "  Recent events:"
kubectl get events -n "${NAMESPACE}" --sort-by=.lastTimestamp 2>/dev/null | grep -iE "OOM|Killing|BackOff|CrashLoop" | tail -5 || echo "  (checking wider event log...)"
kubectl get events -n "${NAMESPACE}" --sort-by=.lastTimestamp 2>/dev/null | tail -10

# ════════════════════════════════════════════════════════════════════
# STEP 4: Fire Alertmanager webhook
# ════════════════════════════════════════════════════════════════════
INCIDENT_NAME=""

if [[ "${SKIP_ALERT}" == "false" ]]; then
  step "Step 4/7: Firing Alertmanager Alert"
  echo "  Gateway:   ${GATEWAY_URL}"
  echo "  Alert:     PodOOMKilled (critical, firing)"
  echo "  Service:   checkout-api"

  # Get the actual pod name and restart count for the alert
  POD_NAME=$(kubectl get pods -l app=checkout-api -n "${NAMESPACE}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "checkout-api-unknown")
  RESTART_COUNT=$(kubectl get pods -l app=checkout-api -n "${NAMESPACE}" -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo "0")
  FINGERPRINT="demo-$(printf '%08x' $((RANDOM*RANDOM%4294967295)))"
  NOW="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"

  PAYLOAD=$(cat <<JSON
{
  "version": "4",
  "groupKey": "{}:PodOOMKilled",
  "truncatedAlerts": 0,
  "status": "firing",
  "receiver": "kubesynapse-incidents",
  "groupLabels": {"alertname": "PodOOMKilled", "severity": "critical"},
  "commonLabels": {
    "alertname": "PodOOMKilled",
    "severity": "critical",
    "service": "checkout-api",
    "environment": "demo",
    "pod": "${POD_NAME}",
    "restart_count": "${RESTART_COUNT}"
  },
  "commonAnnotations": {
    "summary": "checkout-api pod OOMKilled with ${RESTART_COUNT} restarts",
    "description": "Pod ${POD_NAME} in namespace default has been OOMKilled (exit code 137) and restarted ${RESTART_COUNT} times. Memory limit is 64Mi. The pod is in CrashLoopBackOff.",
    "runbook_url": "https://runbooks.example.com/checkout-api/oom"
  },
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "PodOOMKilled",
        "severity": "critical",
        "service": "checkout-api",
        "environment": "demo",
        "pod": "${POD_NAME}",
        "restart_count": "${RESTART_COUNT}",
        "fingerprint": "${FINGERPRINT}"
      },
      "annotations": {
        "summary": "checkout-api pod OOMKilled with ${RESTART_COUNT} restarts",
        "description": "Pod ${POD_NAME} in namespace default has been OOMKilled (exit code 137) and restarted ${RESTART_COUNT} times. Memory limit is 64Mi. The pod is in CrashLoopBackOff."
      },
      "startsAt": "${NOW}",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus.example.com/graph?fingerprint=${FINGERPRINT}",
      "fingerprint": "${FINGERPRINT}"
    }
  ]
}
JSON
)

  URI="${GATEWAY_URL}/api/v1/webhooks/alertmanager?namespace=${NAMESPACE}"
  HTTP_CODE=$(curl -sS -o /tmp/kubesynapse-triage-alert.json -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST \
    --data "${PAYLOAD}" \
    --max-time 30 \
    "${URI}") || { err "curl failed"; exit 1; }

  if [[ "${HTTP_CODE}" != "200" && "${HTTP_CODE}" != "201" && "${HTTP_CODE}" != "202" ]]; then
    err "Webhook POST failed (HTTP ${HTTP_CODE}):"
    cat /tmp/kubesynapse-triage-alert.json 2>/dev/null
    exit 1
  fi

  ok "Alert accepted by gateway"
  INCIDENT_NAME=$(python3 -c "
import json, sys
with open('/tmp/kubesynapse-triage-alert.json') as f:
    data = json.load(f)
results = data.get('results') or []
if results:
    print(results[0].get('name',''))
" 2>/dev/null || true)

  if [[ -n "${INCIDENT_NAME}" ]]; then
    echo "${INCIDENT_NAME}" > /tmp/kubesynapse-last-incident.txt
    echo "  Incident:  ${INCIDENT_NAME}"
  fi
else
  info "Skipping alert (--skip-alert)"
fi

# ════════════════════════════════════════════════════════════════════
# STEP 5: Trigger the workflow
# ════════════════════════════════════════════════════════════════════
step "Step 5/7: Triggering Incident Auto-Triage Workflow"
echo "  Workflow: ${WORKFLOW_NAME}"
echo "  Input:    ${WORKFLOW_INPUT:0:80}..."

TRIGGER_URI="${GATEWAY_URL}/api/v1/workflows/${WORKFLOW_NAME}/trigger?namespace=${NAMESPACE}"
TRIGGER_BODY=$(python3 -c "import json,sys; print(json.dumps({'input':sys.argv[1]}))" "${WORKFLOW_INPUT}")

HTTP_CODE=$(curl -sS -o /tmp/kubesynapse-triage-trigger.json -w "%{http_code}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  --data "${TRIGGER_BODY}" \
  --max-time 30 \
  "${TRIGGER_URI}") || { err "curl trigger failed"; exit 1; }

if [[ "${HTTP_CODE}" != "200" && "${HTTP_CODE}" != "201" && "${HTTP_CODE}" != "202" ]]; then
  err "Workflow trigger failed (HTTP ${HTTP_CODE}):"
  cat /tmp/kubesynapse-triage-trigger.json 2>/dev/null
  exit 1
fi

ok "Workflow trigger accepted"

# ════════════════════════════════════════════════════════════════════
# STEP 6: Wait for workflow run and link incident
# ════════════════════════════════════════════════════════════════════
step "Step 6/7: Waiting for Workflow Run"
info "Waiting up to ${WAIT_SECONDS}s for operator to create a workflow run..."
RUN_ID=""
DEADLINE=$(( $(date +%s) + WAIT_SECONDS ))
while [[ $(date +%s) -lt ${DEADLINE} ]]; do
  sleep 3
  STATUS_JSON=$(curl -sS \
    -H "Authorization: Bearer ${TOKEN}" \
    --max-time 10 \
    "${GATEWAY_URL}/api/v1/workflows/${WORKFLOW_NAME}/status?namespace=${NAMESPACE}" 2>/dev/null || echo "{}")
  RUN_ID=$(echo "${STATUS_JSON}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('runId') or data.get('run_id') or data.get('lastRunId') or '')
except Exception:
    print('')
" 2>/dev/null)
  [[ -n "${RUN_ID}" ]] && break
done

if [[ -n "${RUN_ID}" ]]; then
  ok "Workflow run created: ${RUN_ID}"
else
  warn "Operator has not yet produced a run id. Check: kubectl get agentworkflow ${WORKFLOW_NAME}"
fi

# Link incident to workflow run
if [[ -n "${INCIDENT_NAME}" && -n "${RUN_ID}" ]]; then
  PATCH_BODY=$(python3 -c "import json; print(json.dumps({'workflow_run_id':'${RUN_ID}','message':'Linked to workflow ${WORKFLOW_NAME} (run ${RUN_ID})'}))")

  HTTP_CODE=$(curl -sS -o /tmp/kubesynapse-triage-patch.json -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -X PATCH \
    --data "${PATCH_BODY}" \
    --max-time 15 \
    "${GATEWAY_URL}/api/v1/incidents/${INCIDENT_NAME}?namespace=${NAMESPACE}") 2>/dev/null || true
  [[ "${HTTP_CODE}" == "200" || "${HTTP_CODE}" == "201" ]] && ok "Incident linked to workflow run"
fi

# ════════════════════════════════════════════════════════════════════
# STEP 7: Wait for workflow completion and display report
# ════════════════════════════════════════════════════════════════════
step "Step 7/7: Monitoring Workflow Execution"

if [[ -n "${RUN_ID}" ]]; then
  info "Watching workflow status (checking every 10s)..."
  COMPLETION_DEADLINE=$(( $(date +%s) + 600 ))
  LAST_PHASE=""
  while [[ $(date +%s) -lt ${COMPLETION_DEADLINE} ]]; do
    sleep 10
    STATUS_JSON=$(curl -sS \
      -H "Authorization: Bearer ${TOKEN}" \
      --max-time 10 \
      "${GATEWAY_URL}/api/v1/workflows/${WORKFLOW_NAME}/status?namespace=${NAMESPACE}" 2>/dev/null || echo "{}")
    PHASE=$(echo "${STATUS_JSON}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('phase') or data.get('status') or data.get('state') or '')
except Exception:
    print('')
" 2>/dev/null)
    if [[ "${PHASE}" != "${LAST_PHASE}" ]]; then
      echo "  [$(date +%H:%M:%S)] Workflow phase: ${PHASE:-unknown}"
      LAST_PHASE="${PHASE}"
    fi
    if [[ "${PHASE}" == "completed" || "${PHASE}" == "succeeded" || "${PHASE}" == "failed" || "${PHASE}" == "error" ]]; then
      break
    fi
  done

  echo ""
  echo "  Final workflow status: ${PHASE:-unknown}"

  # Try to fetch the incident report from the workflow artifacts
  echo ""
  info "Attempting to retrieve incident report from workflow artifacts..."
  REPORT=$(curl -sS \
    -H "Authorization: Bearer ${TOKEN}" \
    --max-time 15 \
    "${GATEWAY_URL}/api/v1/workflows/${WORKFLOW_NAME}/runs/${RUN_ID}/artifacts/incident-report.md?namespace=${NAMESPACE}" 2>/dev/null || true)
  if [[ -n "${REPORT}" && "${REPORT}" != *"not found"* && "${REPORT}" != *"error"* ]]; then
    echo ""
    echo -e "${GREEN}${BOLD}═══ INCIDENT REPORT ═══${NC}"
    echo "${REPORT}"
  else
    info "Report not yet available in artifacts. Check the Observatory UI or pod logs."
  fi
fi

# ════════════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}${BOLD}═══ Incident Auto-Triage Demo Summary ═══${NC}"
echo "  Incident:  ${INCIDENT_NAME:-<none>}"
echo "  Workflow:  ${WORKFLOW_NAME}"
echo "  Run:       ${RUN_ID:-<pending>}"
echo "  Phase:     ${PHASE:-<unknown>}"
if [[ -n "${RUN_ID}" ]]; then
  echo "  Observatory: ${GATEWAY_URL}/observatory/${RUN_ID}"
fi
echo ""
echo -e "${CYAN}Next steps:${NC}"
echo "  • Watch pods:    kubectl get pods -n default | grep -E 'triage|checkout'"
echo "  • Check status:  curl -sH \"Authorization: Bearer \${TOKEN}\" ${GATEWAY_URL}/api/v1/workflows/${WORKFLOW_NAME}/status?namespace=${NAMESPACE} | python3 -m json.tool"
echo "  • Watch events:  kubectl get events -n default --sort-by=.lastTimestamp | tail -20"
if [[ -n "${INCIDENT_NAME}" ]]; then
  echo "  • Report:        ./scripts/incidents/generate-incident-report.sh --incident-name ${INCIDENT_NAME}"
fi

# ════════════════════════════════════════════════════════════════════
# Cleanup
# ════════════════════════════════════════════════════════════════════
if [[ "${CLEANUP}" == "true" ]]; then
  step "Cleanup: Removing Demo App"
  kubectl delete -f "${DEMO_APP_DIR}/manifests.yaml" 2>&1
  ok "Demo app removed"
fi

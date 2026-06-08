#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# KubeSynapse — Trigger a workflow and link it to an incident
# ────────────────────────────────────────────────────────────────────
# Triggers an AgentWorkflow by name (POST /api/v1/workflows/{name}/trigger),
# then patches the named incident with the resulting run id so the
# Incidents console can deep-link into the Observatory.
#
# Usage:
#   ./scripts/incidents/trigger-workflow-and-link.sh
#   ./scripts/incidents/trigger-workflow-and-link.sh --incident-name "alert-..." --workflow-name secure-incident-mesh
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
. "${SCRIPT_DIR}/_common.sh"

NAMESPACE="default"
INCIDENT_NAME=""
WORKFLOW_NAME="secure-incident-mesh"
WORKFLOW_INPUT="Investigate the active incident and produce an operator-ready remediation plan."
WAIT_SECONDS=30

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace)      NAMESPACE="$2"; shift 2 ;;
    --incident-name)  INCIDENT_NAME="$2"; shift 2 ;;
    --workflow-name)  WORKFLOW_NAME="$2"; shift 2 ;;
    --input)          WORKFLOW_INPUT="$2"; shift 2 ;;
    --wait)           WAIT_SECONDS="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

resolve_context 8080
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
TOKEN="${KUBESYNAPSE_API_TOKEN:-}"

if [[ -z "${INCIDENT_NAME}" && -f /tmp/kubesynapse-last-incident.txt ]]; then
  INCIDENT_NAME="$(cat /tmp/kubesynapse-last-incident.txt | tr -d '[:space:]')"
  info "Reusing last-fired incident: ${INCIDENT_NAME}"
fi

if [[ -z "${INCIDENT_NAME}" ]]; then
  err "No --incident-name provided and no previous incident recorded. Run fire-alertmanager-alert.sh first."
  exit 1
fi

# ── 1) Trigger workflow ─────────────────────────────────────────────
TRIGGER_URI="${GATEWAY_URL}/api/v1/workflows/${WORKFLOW_NAME}/trigger?namespace=${NAMESPACE}"
TRIGGER_BODY=$(jq -nc --arg input "${WORKFLOW_INPUT}" '{input:$input}')

echo ""
echo -e "${CYAN}═══ Triggering workflow ═══${NC}"
echo "  Workflow: ${WORKFLOW_NAME}"
echo "  Input:    ${WORKFLOW_INPUT:0:60}..."

HTTP_CODE=$(curl -sS -o /tmp/kubesynapse-trigger-response.json -w "%{http_code}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  --data "${TRIGGER_BODY}" \
  --max-time 30 \
  "${TRIGGER_URI}") || { err "curl trigger failed"; exit 1; }

if [[ "${HTTP_CODE}" != "200" && "${HTTP_CODE}" != "201" && "${HTTP_CODE}" != "202" ]]; then
  err "Workflow trigger failed (HTTP ${HTTP_CODE}):"
  cat /tmp/kubesynapse-trigger-response.json 2>/dev/null
  exit 1
fi

ok "Workflow trigger accepted"
cat /tmp/kubesynapse-trigger-response.json | python3 -m json.tool 2>/dev/null || cat /tmp/kubesynapse-trigger-response.json
echo ""

# ── 2) Wait briefly for the operator to create a run ────────────────
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

if [[ -z "${RUN_ID}" ]]; then
  warn "Operator has not yet produced a run id. Linking the incident with the workflow reference only."
fi

# ── 3) Patch the incident to link workflow_run_id ──────────────────
PATCH_BODY=$(jq -nc --arg rid "${RUN_ID}" --arg msg "Linked to workflow ${WORKFLOW_NAME} (run ${RUN_ID})" \
  '{workflow_run_id:$rid, message:$msg}')

HTTP_CODE=$(curl -sS -o /tmp/kubesynapse-patch-response.json -w "%{http_code}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X PATCH \
  --data "${PATCH_BODY}" \
  --max-time 15 \
  "${GATEWAY_URL}/api/v1/incidents/${INCIDENT_NAME}?namespace=${NAMESPACE}") || { err "curl patch failed"; exit 1; }

if [[ "${HTTP_CODE}" != "200" && "${HTTP_CODE}" != "201" ]]; then
  err "Incident patch failed (HTTP ${HTTP_CODE}):"
  cat /tmp/kubesynapse-patch-response.json 2>/dev/null
  exit 1
fi

ok "Incident linked to workflow"
echo ""
echo -e "${GREEN}  Incident: ${INCIDENT_NAME}${NC}"
echo "  Workflow: ${WORKFLOW_NAME}"
if [[ -n "${RUN_ID}" ]]; then
  echo "  Run:      ${RUN_ID}"
  echo "  Open:     ${GATEWAY_URL}/observatory/${RUN_ID}"
else
  echo "  Run:      (operator pending — re-run this script after reconciliation)"
fi

echo ""
echo -e "${CYAN}Next:${NC}"
echo "  • Report:  ./scripts/incidents/generate-incident-report.sh --incident-name ${INCIDENT_NAME}"

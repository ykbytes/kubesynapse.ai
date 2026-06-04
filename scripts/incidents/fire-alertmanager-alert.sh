#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# KubeSynapse — Fire example Alertmanager v4 webhook
# ────────────────────────────────────────────────────────────────────
# Sends a realistic Alertmanager v4 payload to the gateway's
# /api/v1/webhooks/alertmanager endpoint to create a firing incident
# that can be picked up by a workflow trigger or investigated in the
# Incidents console.
#
# Usage:
#   ./scripts/incidents/fire-alertmanager-alert.sh
#   ./scripts/incidents/fire-alertmanager-alert.sh --severity critical --alertname PodOOMKilled
#   ./scripts/incidents/fire-alertmanager-alert.sh --namespace prod --resolve
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

NAMESPACE="default"
SEVERITY="warning"
ALERTNAME="DemoHighLatency"
SERVICE="checkout-api"
ENVIRONMENT="demo"
SUMMARY="Checkout API p95 latency above 3s"
DESCRIPTION="p95 latency 3.4s for checkout-api in prod-aks-eastus. Two OOMKilled restarts in the last 5m."
RESOLVE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace)   NAMESPACE="$2"; shift 2 ;;
    --severity)    SEVERITY="$2"; shift 2 ;;
    --alertname)   ALERTNAME="$2"; shift 2 ;;
    --service)     SERVICE="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --summary)     SUMMARY="$2"; shift 2 ;;
    --description) DESCRIPTION="$2"; shift 2 ;;
    --resolve)     RESOLVE=true; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; CYAN=$'\033[0;36m'; NC=$'\033[0m'
info() { echo "${BLUE}[INFO]${NC}  $*"; }
ok()   { echo "${GREEN}[OK]${NC}    $*"; }
warn() { echo "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo "${RED}[ERROR]${NC} $*" >&2; }

# ── Resolve gateway URL & token ──────────────────────────────────────
GATEWAY_PORT=8080
GATEWAY_URL="${KUBESYNAPSE_GATEWAY_URL:-}"

if [[ -z "${GATEWAY_URL}" ]]; then
  if ! ss -lnt 2>/dev/null | grep -q ":${GATEWAY_PORT} "; then
    info "No listener on port ${GATEWAY_PORT} — starting port-forward to kubesynapse-api-gateway"
    kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway "${GATEWAY_PORT}:8080" >/tmp/kubesynapse-pf-gateway.log 2>&1 &
    sleep 4
  fi
  GATEWAY_URL="http://127.0.0.1:${GATEWAY_PORT}"
fi

TOKEN="${KUBESYNAPSE_API_TOKEN:-}"
if [[ -z "${TOKEN}" ]]; then
  TOKEN="$(kubectl get secret kubesynapse-llm-api-keys -n kubesynapse -o jsonpath='{.data.API_GATEWAY_SHARED_TOKEN}' 2>/dev/null | base64 -d 2>/dev/null || true)"
  [[ -n "${TOKEN}" ]] && ok "Loaded gateway token from kubesynapse-llm-api-keys"
fi
if [[ -z "${TOKEN}" ]]; then
  TOKEN="$(kubectl get secret kubesynapse-shared-auth -n kubesynapse -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || true)"
fi
if [[ -z "${TOKEN}" ]]; then
  err "Could not resolve KUBESYNAPSE_API_TOKEN. Set the env var or install the platform with a shared token secret."
  exit 1
fi

# ── Build Alertmanager v4 payload ───────────────────────────────────
FINGERPRINT="demo-$(printf '%08x' $((RANDOM*RANDOM%4294967295)))"
NOW="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
STATUS="firing"
[[ "${RESOLVE}" == "true" ]] && STATUS="resolved"
ENDS_AT="0001-01-01T00:00:00Z"
[[ "${STATUS}" == "resolved" ]] && ENDS_AT="${NOW}"

PAYLOAD=$(cat <<JSON
{
  "version": "4",
  "groupKey": "{}:${ALERTNAME}",
  "truncatedAlerts": 0,
  "status": "${STATUS}",
  "receiver": "kubesynapse-incidents",
  "groupLabels": {"alertname": "${ALERTNAME}", "severity": "${SEVERITY}"},
  "commonLabels": {
    "alertname": "${ALERTNAME}",
    "severity": "${SEVERITY}",
    "service": "${SERVICE}",
    "environment": "${ENVIRONMENT}"
  },
  "commonAnnotations": {
    "summary": "${SUMMARY}",
    "description": "${DESCRIPTION}",
    "runbook_url": "https://runbooks.example.com/${SERVICE}/latency"
  },
  "alerts": [
    {
      "status": "${STATUS}",
      "labels": {
        "alertname": "${ALERTNAME}",
        "severity": "${SEVERITY}",
        "service": "${SERVICE}",
        "environment": "${ENVIRONMENT}",
        "fingerprint": "${FINGERPRINT}"
      },
      "annotations": {
        "summary": "${SUMMARY}",
        "description": "${DESCRIPTION}"
      },
      "startsAt": "${NOW}",
      "endsAt": "${ENDS_AT}",
      "generatorURL": "http://prometheus.example.com/graph?fingerprint=${FINGERPRINT}",
      "fingerprint": "${FINGERPRINT}"
    }
  ]
}
JSON
)

echo ""
echo -e "${CYAN}═══ Firing Alertmanager alert ═══${NC}"
echo "  Gateway:   ${GATEWAY_URL}"
echo "  Namespace: ${NAMESPACE}"
echo "  Alert:     ${ALERTNAME} (${SEVERITY}, ${STATUS})"
echo "  Service:   ${SERVICE}"
echo ""

URI="${GATEWAY_URL}/api/v1/webhooks/alertmanager?namespace=${NAMESPACE}"
HTTP_CODE=$(curl -sS -o /tmp/kubesynapse-firing-response.json -w "%{http_code}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  --data "${PAYLOAD}" \
  --max-time 30 \
  "${URI}") || { err "curl failed"; exit 1; }

if [[ "${HTTP_CODE}" != "200" && "${HTTP_CODE}" != "201" && "${HTTP_CODE}" != "202" ]]; then
  err "Webhook POST failed (HTTP ${HTTP_CODE}):"
  cat /tmp/kubesynapse-firing-response.json 2>/dev/null
  exit 1
fi

ok "Webhook accepted by gateway"
echo ""
cat /tmp/kubesynapse-firing-response.json | python3 -m json.tool 2>/dev/null || cat /tmp/kubesynapse-firing-response.json
echo ""

INCIDENT_NAME=$(python3 -c "
import json, sys
with open('/tmp/kubesynapse-firing-response.json') as f:
    data = json.load(f)
results = data.get('results') or []
if results:
    print(results[0].get('name',''))
" 2>/dev/null || true)

if [[ -n "${INCIDENT_NAME}" ]]; then
  echo "${INCIDENT_NAME}" > /tmp/kubesynapse-last-incident.txt
  echo ""
  echo -e "${CYAN}Incident created:${NC}"
  echo "  name:     ${INCIDENT_NAME}"
  echo "  inspect:  curl -H \"Authorization: Bearer \${TOKEN}\" ${GATEWAY_URL}/api/v1/incidents/${INCIDENT_NAME}"
  echo "  trigger:  ./scripts/incidents/trigger-workflow-and-link.sh --incident-name ${INCIDENT_NAME}"
  echo "  report:   ./scripts/incidents/generate-incident-report.sh --incident-name ${INCIDENT_NAME}"
fi

#!/usr/bin/env bash
set -euo pipefail

GATEWAY_URL="${AGENT_GATEWAY_URL:-http://localhost:8080}"
NAMESPACE="${AGENT_NAMESPACE:-default}"
WEBHOOK_SECRET="${INCIDENT_WEBHOOK_SECRET:-demo-incident-webhook-secret}"
TIMESTAMP="$(date +%s)"

PAYLOAD='{
  "service": "api-gateway",
  "severity": "critical",
  "alert_name": "Gateway5xxSpike",
  "summary": "5xx error rate exceeded threshold for the API gateway",
  "namespace": "kubesynapse",
  "runbook": "Inspect gateway pods, recent deploys, ingress behavior, and backing services"
}'

if command -v openssl >/dev/null 2>&1; then
  SIGNATURE="$(printf '%s' "${PAYLOAD}" | openssl dgst -sha256 -hmac "${WEBHOOK_SECRET}" -hex | sed 's/^.* //')"
else
  echo "openssl is required to compute the HMAC signature" >&2
  exit 1
fi

curl -sS -X POST "${GATEWAY_URL}/api/v1/webhooks/incident-alerts/invoke?namespace=${NAMESPACE}" \
  -H "Content-Type: application/json" \
  -H "X-kubesynapse-Timestamp: ${TIMESTAMP}" \
  -H "X-kubesynapse-Signature: ${SIGNATURE}" \
  -d "${PAYLOAD}"

echo

#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${AGENT_GATEWAY_TOKEN:-}" ]]; then
  echo "AGENT_GATEWAY_TOKEN is not set" >&2
  exit 1
fi

GATEWAY_URL="${AGENT_GATEWAY_URL:-http://localhost:8080}"
NAMESPACE="${AGENT_NAMESPACE:-default}"

echo "Creating webhook receiver in namespace ${NAMESPACE}..."
curl -sS -X POST "${GATEWAY_URL}/api/v1/webhooks?namespace=${NAMESPACE}" \
  -H "Authorization: Bearer ${AGENT_GATEWAY_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "incident-alerts",
    "secret_ref": "default/incident-webhook-secret#hmac-key",
    "ip_allowlist": [],
    "rate_limit": 30,
    "max_payload_bytes": 1048576,
    "enabled": true
  }'

echo
echo "Creating workflow trigger in namespace ${NAMESPACE}..."
curl -sS -X POST "${GATEWAY_URL}/api/v1/workflow-triggers?namespace=${NAMESPACE}" \
  -H "Authorization: Bearer ${AGENT_GATEWAY_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "incident-alert-trigger",
    "source_ref": "incident-alerts",
    "source_kind": "WebhookReceiver",
    "event_filter": {
      "conditions": [
        { "field": "severity", "operator": "equals", "value": "critical" },
        { "field": "service", "operator": "equals", "value": "api-gateway" }
      ]
    },
    "workflow_ref": {
      "name": "incident-webhook-response",
      "namespace": "default"
    },
    "max_retries": 1,
    "backoff_seconds": 30,
    "enabled": true
  }'

echo
echo "Receiver and trigger bootstrap requests sent."

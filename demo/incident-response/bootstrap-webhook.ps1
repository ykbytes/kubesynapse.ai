$ErrorActionPreference = "Stop"

if (-not $env:AGENT_GATEWAY_TOKEN) {
  throw "AGENT_GATEWAY_TOKEN is not set"
}

$gatewayUrl = if ($env:AGENT_GATEWAY_URL) { $env:AGENT_GATEWAY_URL } else { "http://localhost:8080" }
$namespace = if ($env:AGENT_NAMESPACE) { $env:AGENT_NAMESPACE } else { "default" }
$headers = @{
  Authorization = "Bearer $($env:AGENT_GATEWAY_TOKEN)"
  "Content-Type" = "application/json"
}

$receiverBody = @{
  name = "incident-alerts"
  secret_ref = "default/incident-webhook-secret#hmac-key"
  ip_allowlist = @()
  rate_limit = 30
  max_payload_bytes = 1048576
  enabled = $true
} | ConvertTo-Json -Depth 6

$triggerBody = @{
  name = "incident-alert-trigger"
  source_ref = "incident-alerts"
  source_kind = "WebhookReceiver"
  event_filter = @{
    conditions = @(
      @{ field = "severity"; operator = "equals"; value = "critical" },
      @{ field = "service"; operator = "equals"; value = "api-gateway" }
    )
  }
  workflow_ref = @{
    name = "incident-webhook-response"
    namespace = "default"
  }
  max_retries = 1
  backoff_seconds = 30
  enabled = $true
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Method Post -Uri "$gatewayUrl/api/v1/webhooks?namespace=$namespace" -Headers $headers -Body $receiverBody
Invoke-RestMethod -Method Post -Uri "$gatewayUrl/api/v1/workflow-triggers?namespace=$namespace" -Headers $headers -Body $triggerBody

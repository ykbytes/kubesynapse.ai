$ErrorActionPreference = "Stop"

$gatewayUrl = if ($env:AGENT_GATEWAY_URL) { $env:AGENT_GATEWAY_URL } else { "http://localhost:8080" }
$namespace = if ($env:AGENT_NAMESPACE) { $env:AGENT_NAMESPACE } else { "default" }
$secret = if ($env:INCIDENT_WEBHOOK_SECRET) { $env:INCIDENT_WEBHOOK_SECRET } else { "demo-incident-webhook-secret" }
$timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()

$payloadObject = @{
  service = "api-gateway"
  severity = "critical"
  alert_name = "Gateway5xxSpike"
  summary = "5xx error rate exceeded threshold for the API gateway"
  namespace = "kubesynapse"
  runbook = "Inspect gateway pods, recent deploys, ingress behavior, and backing services"
}

$payload = $payloadObject | ConvertTo-Json -Depth 6 -Compress

$hmac = [System.Security.Cryptography.HMACSHA256]::new([System.Text.Encoding]::UTF8.GetBytes($secret))
$hashBytes = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($payload))
$signature = ([System.BitConverter]::ToString($hashBytes)).Replace("-", "").ToLowerInvariant()

$headers = @{
  "Content-Type" = "application/json"
  "X-kubesynapse-Timestamp" = $timestamp
  "X-kubesynapse-Signature" = $signature
}

Invoke-RestMethod -Method Post -Uri "$gatewayUrl/api/v1/webhooks/incident-alerts/invoke?namespace=$namespace" -Headers $headers -Body $payload

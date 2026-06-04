# ────────────────────────────────────────────────────────────────────
# KubeSynapse — Fire example Alertmanager v4 webhook
# ────────────────────────────────────────────────────────────────────
# Sends a realistic Alertmanager v4 payload to the gateway's
# /api/v1/webhooks/alertmanager endpoint to create a firing incident
# that can be picked up by a workflow trigger or investigated in the
# Incidents console.
#
# Usage:
#   .\scripts\incidents\fire-alertmanager-alert.ps1
#   .\scripts\incidents\fire-alertmanager-alert.ps1 -Severity critical -Alertname PodOOMKilled
#   .\scripts\incidents\fire-alertmanager-alert.ps1 -Namespace prod -Resolve
# ────────────────────────────────────────────────────────────────────
[CmdletBinding()]
param(
  [string]$Namespace = "default",
  [ValidateSet("critical", "warning", "info")]
  [string]$Severity = "warning",
  [string]$Alertname = "DemoHighLatency",
  [string]$Service = "checkout-api",
  [string]$Environment = "demo",
  [string]$Summary = "Checkout API p95 latency above 3s",
  [string]$Description = "p95 latency 3.4s for checkout-api in prod-aks-eastus. Two OOMKilled restarts in the last 5m.",
  [switch]$Resolve
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

# ── Resolve gateway URL & token ──────────────────────────────────────
$GatewayPort = 8080
$GatewayUrl = $env:KUBESYNAPSE_GATEWAY_URL
if (-not $GatewayUrl) {
  $PortForward = $false
  $ExistingPf = Get-NetTCPConnection -LocalPort $GatewayPort -State Listen -ErrorAction SilentlyContinue
  if (-not $ExistingPf) {
    Write-Host "[INFO] No listener on port $GatewayPort — starting port-forward to kubesynapse-api-gateway..." -ForegroundColor Blue
    Start-Process -NoNewWindow -FilePath kubectl -ArgumentList @(
      "port-forward","-n","kubesynapse","svc/kubesynapse-api-gateway","${GatewayPort}:8080"
    ) | Out-Null
    $PortForward = $true
    Start-Sleep -Seconds 4
  }
  $GatewayUrl = "http://127.0.0.1:${GatewayPort}"
}

$Token = $env:KUBESYNAPSE_API_TOKEN
if (-not $Token) {
  try {
    $SecretJson = kubectl get secret kubesynapse-llm-api-keys -n kubesynapse -o json --ignore-not-found
    if ($SecretJson) {
      $SecretObj = $SecretJson | ConvertFrom-Json
      $Encoded = $SecretObj.data.API_GATEWAY_SHARED_TOKEN
      if ($Encoded) {
        $Token = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Encoded))
        Write-Host "[OK]   Loaded gateway token from kubesynapse-llm-api-keys" -ForegroundColor Green
      }
    }
  } catch {}
}
if (-not $Token) {
  $SharedTokenSecret = kubectl get secret kubesynapse-shared-auth -n kubesynapse -o json --ignore-not-found
  if ($SharedTokenSecret) {
    $Obj = $SharedTokenSecret | ConvertFrom-Json
    $Enc = $Obj.data.token
    if ($Enc) { $Token = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Enc)) }
  }
}
if (-not $Token) {
  throw "Could not resolve KUBESYNAPSE_API_TOKEN. Set the env var or install the platform with a shared token secret."
}

# ── Build Alertmanager v4 payload ───────────────────────────────────
$Hex = ([Guid]::NewGuid().ToString("N")).Substring(0, 12)
$Fingerprint = "demo-$Hex"
$Now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$Status = if ($Resolve) { "resolved" } else { "firing" }

$Payload = [ordered]@{
  version           = "4"
  groupKey          = "group:{0}" -f $Alertname
  truncatedAlerts   = 0
  status            = $Status
  receiver          = "kubesynapse-incidents"
  groupLabels       = @{ alertname = $Alertname; severity = $Severity }
  commonLabels      = @{
    alertname  = $Alertname
    severity   = $Severity
    service    = $Service
    environment = $Environment
  }
  commonAnnotations = @{
    summary     = $Summary
    description = $Description
    runbook_url = "https://runbooks.example.com/${Service}/latency"
  }
  alerts = @(
    [ordered]@{
      status        = $Status
      labels        = @{
        alertname   = $Alertname
        severity    = $Severity
        service     = $Service
        environment = $Environment
        fingerprint = $Fingerprint
      }
      annotations   = @{
        summary     = $Summary
        description = $Description
      }
      startsAt      = $Now
      endsAt        = if ($Resolve) { $Now } else { "0001-01-01T00:00:00Z" }
      generatorURL  = "http://prometheus.example.com/graph?fingerprint=$Fingerprint"
      fingerprint   = $Fingerprint
    }
  )
}

$Json = $Payload | ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "═══ Firing Alertmanager alert ═══" -ForegroundColor Cyan
Write-Host "  Gateway:   $GatewayUrl"
Write-Host "  Namespace: $Namespace"
Write-Host "  Alert:     $Alertname ($Severity, $Status)"
Write-Host "  Service:   $Service"
Write-Host ""

$Uri = "${GatewayUrl}/api/v1/webhooks/alertmanager?namespace=$Namespace"
$Headers = @{ Authorization = "Bearer $Token"; "Content-Type" = "application/json" }

try {
  $Response = Invoke-RestMethod -Uri $Uri -Method Post -Headers $Headers -Body $Json -TimeoutSec 30
} catch {
  $StatusCode = $_.Exception.Response.StatusCode.value__
  throw "Webhook POST failed (HTTP $StatusCode): $($_.Exception.Message)"
}

Write-Host "[OK]   Webhook accepted by gateway" -ForegroundColor Green
Write-Host ""
$Response | Format-List

if ($Response.results -and $Response.results.Count -gt 0) {
  $First = $Response.results[0]
  if ($First.name) {
    Write-Host ""
    Write-Host "Incident created:" -ForegroundColor Cyan
    Write-Host "  name:        $($First.name)"
    Write-Host "  status:      $($First.status)"
    Write-Host "  severity:    $($First.severity)"
    Write-Host ""
    Write-Host "Next:" -ForegroundColor Cyan
    Write-Host "  • Inspect:  curl -H `"Authorization: Bearer $Token`" $GatewayUrl/api/v1/incidents/$($First.name)"
    Write-Host "  • Trigger:  .\scripts\incidents\trigger-workflow-and-link.ps1 -IncidentName $($First.name)"
    Write-Host "  • Report:   .\scripts\incidents\generate-incident-report.ps1 -IncidentName $($First.name)"
    $First.name | Out-File -FilePath (Join-Path $env:TEMP "kubesynapse-last-incident.txt") -Encoding ascii -NoNewline
  }
}

# ────────────────────────────────────────────────────────────────────
# KubeSynapse — Trigger a workflow and link it to an incident
# ────────────────────────────────────────────────────────────────────
# Triggers an AgentWorkflow by name (POST /api/v1/workflows/{name}/trigger),
# then patches the named incident with the resulting run id so the
# Incidents console can deep-link into the Observatory.
#
# Usage:
#   .\scripts\incidents\trigger-workflow-and-link.ps1
#   .\scripts\incidents\trigger-workflow-and-link.ps1 -IncidentName "alert-DemoHighLatency-abc123" -WorkflowName secure-incident-mesh
# ────────────────────────────────────────────────────────────────────
[CmdletBinding()]
param(
  [string]$Namespace = "default",
  [string]$IncidentName = "",
  [string]$WorkflowName = "secure-incident-mesh",
  [string]$WorkflowInput = "Investigate the active incident and produce an operator-ready remediation plan.",
  [int]$WaitSeconds = 30
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# ── Resolve gateway URL & token (re-uses the same logic as fire-...) ──
. (Join-Path $ScriptDir "_common.ps1")
$Ctx = Resolve-KubeSynapseContext -Port 8080

$Token = $Ctx.Token
$GatewayUrl = $Ctx.GatewayUrl

# ── Resolve incident name (last-fired) ──────────────────────────────
if (-not $IncidentName) {
  $LastFile = Join-Path $env:TEMP "kubesynapse-last-incident.txt"
  if (Test-Path $LastFile) {
    $IncidentName = (Get-Content $LastFile -Raw).Trim()
    Write-Host "[INFO] Reusing last-fired incident: $IncidentName" -ForegroundColor Blue
  } else {
    throw "No -IncidentName provided and no previous incident recorded. Run fire-alertmanager-alert.ps1 first."
  }
}

# ── 1) Trigger workflow ─────────────────────────────────────────────
$TriggerUri = "${GatewayUrl}/api/v1/workflows/${WorkflowName}/trigger?namespace=$Namespace"
$TriggerBody = @{ input = $WorkflowInput } | ConvertTo-Json
$Headers = @{ Authorization = "Bearer $Token"; "Content-Type" = "application/json" }

Write-Host ""
Write-Host "═══ Triggering workflow ═══" -ForegroundColor Cyan
Write-Host "  Workflow: $WorkflowName"
Write-Host "  Input:    $($WorkflowInput.Substring(0, [Math]::Min(60, $WorkflowInput.Length)))..."
Write-Host ""

try {
  $TriggerResp = Invoke-RestMethod -Uri $TriggerUri -Method Post -Headers $Headers -Body $TriggerBody -TimeoutSec 30
} catch {
  $StatusCode = $_.Exception.Response.StatusCode.value__
  throw "Workflow trigger failed (HTTP $StatusCode): $($_.Exception.Message)"
}

ok "Workflow trigger accepted"
$TriggerResp | Format-List Status, Generation, Message

# ── 2) Wait briefly for the operator to create a run ────────────────
Write-Host ""
Write-Host "[INFO] Waiting up to ${WaitSeconds}s for operator to create a workflow run..." -ForegroundColor Blue
$RunId = $null
$Deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $Deadline -and -not $RunId) {
  Start-Sleep -Seconds 3
  try {
    $StatusUri = "${GatewayUrl}/api/v1/workflows/${WorkflowName}/status?namespace=$Namespace"
    $Status = Invoke-RestMethod -Uri $StatusUri -Method Get -Headers $Headers -TimeoutSec 10
    $RunId = $Status.runId ?? $Status.run_id ?? $Status.lastRunId ?? $null
    if ($RunId) { break }
  } catch {}
}

if (-not $RunId) {
  warn "Operator has not yet produced a run id. Linking the incident with the workflow reference only."
}

# ── 3) Patch the incident to link workflow_run_id ──────────────────
$PatchUri = "${GatewayUrl}/api/v1/incidents/${IncidentName}?namespace=$Namespace"
$PatchBody = @{
  workflow_run_id = $RunId
  message         = "Linked to workflow ${WorkflowName} (run ${RunId})"
} | ConvertTo-Json

try {
  $Updated = Invoke-RestMethod -Uri $PatchUri -Method Patch -Headers $Headers -Body $PatchBody -TimeoutSec 15
} catch {
  $StatusCode = $_.Exception.Response.StatusCode.value__
  throw "Incident patch failed (HTTP $StatusCode): $($_.Exception.Message)"
}

ok "Incident linked to workflow"
Write-Host ""
Write-Host "  Incident: $IncidentName" -ForegroundColor Green
Write-Host "  Workflow: $WorkflowName"
if ($RunId) {
  Write-Host "  Run:      $RunId"
  Write-Host "  Open:     $GatewayUrl/observatory/$RunId"
} else {
  Write-Host "  Run:      (operator pending — re-run this script after reconciliation)"
}

Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  • Report:  .\scripts\incidents\generate-incident-report.ps1 -IncidentName $IncidentName"

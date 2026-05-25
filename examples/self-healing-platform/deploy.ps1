<#
.SYNOPSIS
  Deploy the Self-Healing Platform demo.
  Includes a HITL approval gate — human must approve remediation.
#>
param(
    [string]$Namespace = "default",
    [string]$Context = "",
    [int]$WaitTimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$kctx = if ($Context) { @("--context", $Context) } else { @() }

Write-Host "=== Self-Healing Platform — Deploy ===" -ForegroundColor Cyan
Write-Host "This demo includes 5 agents + a human approval gate." -ForegroundColor Magenta

$files = @("project-context.yaml", "agents.yaml", "policy.yaml", "workflow.yaml")
foreach ($f in $files) {
    if (-not (Test-Path $f)) { Write-Error "Missing: $f"; exit 1 }
}

Write-Host "[1/4] Applying project context..." -ForegroundColor Yellow
kubectl apply -f project-context.yaml -n $Namespace @kctx

Write-Host "[2/4] Applying 5 agents..." -ForegroundColor Yellow
kubectl apply -f agents.yaml -n $Namespace @kctx

Write-Host "[3/4] Applying policy (includes HITL enforcement)..." -ForegroundColor Yellow
kubectl apply -f policy.yaml -n $Namespace @kctx

Write-Host "[4/4] Applying workflow with approval gate..." -ForegroundColor Yellow
kubectl apply -f workflow.yaml -n $Namespace @kctx

$agents = @("platform-monitor", "incident-triage", "forensics-collector", "remediation-planner", "remediation-executor", "postmortem-writer")
foreach ($agent in $agents) {
    Write-Host "Waiting for $agent sandbox..." -ForegroundColor Yellow
    $deadline = (Get-Date).AddSeconds($WaitTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $pod = kubectl get pods -n $Namespace -l "agent-name=$agent" -o json 2>$null @kctx | ConvertFrom-Json
        if ($pod.items.Count -gt 0 -and $pod.items[0].status.phase -eq "Running") {
            Write-Host "  $agent is Running" -ForegroundColor Green
            break
        }
        Start-Sleep -Seconds 5
    }
}

Write-Host ""
Write-Host "=== Deploy Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Trigger the incident:" -ForegroundColor Cyan
Write-Host "  agentctl workflows trigger self-healing-incident"
Write-Host ""
Write-Host "The workflow will run Steps 1-4 automatically, then PAUSE at Step 5." -ForegroundColor Yellow
Write-Host "A human must approve the remediation plan before execution continues." -ForegroundColor Yellow
Write-Host ""
Write-Host "Check pending approvals:" -ForegroundColor Cyan
Write-Host "  agentctl runs approvals"
Write-Host ""
Write-Host "Approve the fix:" -ForegroundColor Cyan
Write-Host '  agentctl runs approve <approval-name> --reason "Plan looks correct — proceed"'
Write-Host ""
Write-Host "View the full timeline:" -ForegroundColor Cyan
Write-Host "  Web UI > Intelligence > Observatory"
Write-Host ""
Write-Host "Read the postmortem:" -ForegroundColor Cyan
Write-Host "  Web UI > Agents > postmortem-writer > Workspace Files"

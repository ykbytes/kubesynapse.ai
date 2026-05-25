<#
.SYNOPSIS
  Deploy the Daily Standup Bot demo to a KubeSynapse cluster.

.DESCRIPTION
  Validates and applies the project context, agents, policy, and
  workflow manifests. Waits for agent sandboxes to become ready.
#>
param(
    [string]$Namespace = "default",
    [string]$Context = "",
    [int]$WaitTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$kctx = if ($Context) { @("--context", $Context) } else { @() }

Write-Host "=== Daily Standup Bot — Deploy ===" -ForegroundColor Cyan

# Validate YAML exists
$files = @(
    "project-context.yaml",
    "agents.yaml",
    "policy.yaml",
    "workflow.yaml"
)
foreach ($f in $files) {
    if (-not (Test-Path $f)) {
        Write-Error "Missing: $f"
        exit 1
    }
}

# Apply in order
Write-Host "[1/4] Applying project context..." -ForegroundColor Yellow
kubectl apply -f project-context.yaml -n $Namespace @kctx

Write-Host "[2/4] Applying agents..." -ForegroundColor Yellow
kubectl apply -f agents.yaml -n $Namespace @kctx

Write-Host "[3/4] Applying policy..." -ForegroundColor Yellow
kubectl apply -f policy.yaml -n $Namespace @kctx

Write-Host "[4/4] Applying workflow..." -ForegroundColor Yellow
kubectl apply -f workflow.yaml -n $Namespace @kctx

# Wait for agent sandboxes
$agents = @("standup-git", "standup-jira", "standup-scribe")
foreach ($agent in $agents) {
    Write-Host "Waiting for $agent sandbox..." -ForegroundColor Yellow
    $deadline = (Get-Date).AddSeconds($WaitTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $pod = kubectl get pods -n $Namespace -l "agent-name=$agent" -o json 2>$null @kctx | ConvertFrom-Json
        if ($pod.items.Count -gt 0) {
            $status = $pod.items[0].status.phase
            if ($status -eq "Running") {
                Write-Host "  $agent is Running" -ForegroundColor Green
                break
            }
        }
        Start-Sleep -Seconds 5
    }
}

Write-Host ""
Write-Host "=== Deploy Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Trigger the workflow:" -ForegroundColor Cyan
Write-Host "  agentctl workflows trigger daily-standup"
Write-Host ""
Write-Host "Or via API:" -ForegroundColor Cyan
Write-Host '  curl -X POST http://localhost:8080/api/v1/workflows/daily-standup/trigger?namespace=default -H "Authorization: Bearer $TOKEN"'
Write-Host ""
Write-Host "Find the output at:" -ForegroundColor Cyan
Write-Host "  Web UI > Agents > standup-scribe > Workspace Files > standup-*.md"
